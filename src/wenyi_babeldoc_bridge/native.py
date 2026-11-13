"""Python policy adapters over the pinned, bridge-owned Rust stage boundary.

The Python IL is a mutable projection for annotations/TOC policies, not a parser
or writer. Graph aliases and lazy graphics history travel with that projection.
Only the native document and its original parser page map form a checkpoint.
"""

from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args, get_origin


@lru_cache
def _fields(cls: type) -> tuple:
    result = []
    for field in dataclasses.fields(cls):
        annotation = field.type
        many = get_origin(annotation) is list
        choices = get_args(annotation) or (annotation,)
        child = next(
            (choice for choice in choices if dataclasses.is_dataclass(choice)), None
        )
        result.append((field.name, many, child))
    return tuple(result)


def _glyph_key(char: Any) -> tuple | None:
    """Use parser draw identity, never text matching, across native regrouping."""
    if char.render_order is None or not (char.char_unicode or "").strip():
        return None
    return (
        char.xobj_id,
        char.render_order,
        char.sub_render_order,
        char.pdf_character_id,
    )


class Document:
    def __init__(self, native: Any):
        self.native = native
        self.document = None
        self._artifact: dict = {}
        self.refresh()

    @property
    def page(self):
        return self.document.page

    def refresh(self) -> None:
        from babeldoc.format.pdf.document_il import il_version_1 as il

        artifact = json.loads(self.native.artifact())
        aliases = {
            path: paths[0]
            for groups in artifact["shared_alias_paths"].values()
            for paths in groups
            for path in paths
        }
        loaded = {}
        old_paragraphs = {}
        old_glyphs = {}
        if self.document is not None:
            from wenyi_babeldoc_bridge.annotations import _characters

            for page in self.page:
                for index, para in enumerate(page.pdf_paragraph):
                    old_paragraphs[(page.page_number, index)] = para
                    for comp in para.pdf_paragraph_composition:
                        for char in _characters(comp):
                            key = _glyph_key(char)
                            if key is not None:
                                old_glyphs[(page.page_number, key)] = char

        def decode(cls, value, path, page_number=None, paragraph_index=None):
            key = aliases.get(path, path)
            if key in loaded:
                return loaded[key]
            if cls is il.Page:
                page_number = value["page_number"]
            obj = None
            if cls is il.PdfParagraph:
                obj = old_paragraphs.get((page_number, paragraph_index))
            elif cls is il.PdfCharacter:
                draw_key = (
                    value["xobj_id"],
                    value["render_order"],
                    value["sub_render_order"],
                    value["pdf_character_id"],
                )
                obj = old_glyphs.get((page_number, draw_key))
            if obj is None:
                obj = cls()
            loaded[key] = obj
            for name, many, child in _fields(cls):
                item = value[name]
                if child and item is not None:
                    if many:
                        item = [
                            decode(
                                child,
                                row,
                                f"{path}.{name}[{index}]",
                                page_number,
                                index,
                            )
                            for index, row in enumerate(item)
                        ]
                    else:
                        item = decode(child, item, f"{path}.{name}", page_number)
                setattr(obj, name, item)
            return obj

        self.document = decode(il.Document, artifact["document"], "$")
        self._artifact = artifact

    def sync(self) -> None:
        """Import a policy-edited projection without dropping scalar carriers."""
        groups = defaultdict(lambda: defaultdict(list))

        def encode(obj, path):
            kind = type(obj).__name__
            groups[kind][id(obj)].append(path)
            result = {}
            for name, many, child in _fields(type(obj)):
                value = getattr(obj, name)
                if child and value is not None:
                    if many:
                        value = [
                            encode(row, f"{path}.{name}[{index}]")
                            for index, row in enumerate(value)
                        ]
                    else:
                        value = encode(value, f"{path}.{name}")
                result[name] = value
            return result

        document = encode(self.document, "$")
        aliases = {
            kind: sorted(sorted(paths) for paths in objects.values())
            for kind, objects in groups.items()
        }
        self.native.replace_artifact(
            json.dumps(
                {
                    **self._artifact,
                    "document": document,
                    "shared_alias_paths": aliases,
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        )

    def snapshot(self) -> str:
        self.sync()
        return self.native.snapshot()

    @classmethod
    def restore(cls, text: str) -> Document:
        from wenyi_babeldoc_bridge import _native

        return cls(_native.Document.restore(text))


@lru_cache(maxsize=1)
def font_config(language: str, primary: str | None) -> Any:
    from babeldoc.assets import assets
    from wenyi_babeldoc_bridge import _native

    family = assets.get_font_family(language)
    resolved = {}
    for group in ("normal", "script", "fallback", "base"):
        for name in family[group]:
            if name not in resolved:
                path, metadata = assets.get_font_and_metadata(name)
                resolved[name] = {
                    "path": str(path),
                    **{
                        key: metadata[key]
                        for key in ("font_name", "ascent", "descent", "encoding_length")
                    },
                }
    return _native.FontAssets(
        json.dumps({**family, "assets": resolved, "primary": primary})
    )


def parse_prepared_pdf(path, *, config, doc_pdf):
    from wenyi_babeldoc_bridge import _native

    pages = [
        index
        for index in range(len(doc_pdf))
        if config.should_translate_page(index + 1)
    ]
    if not pages:
        raise ValueError("No PDF pages selected")
    return Document(_native.Document.parse(str(path), pages))


class LayoutParser:
    def __init__(self, config):
        self.config = config

    def process(self, docs, pdf):
        from babeldoc.rust_layout_service import project_result

        results = self.config.doc_layout_model.handle_document(
            docs.page,
            pdf,
            self.config,
            lambda *args: None,
        )
        rows = []
        for index, (page, result) in enumerate(results):
            _, mediabox, boxes = project_result(page, result, pdf, index)
            size = pdf[page.page_number].mediabox_size
            rows.append(
                {
                    "page_number": page.page_number,
                    "mediabox": mediabox or [size.x, size.y],
                    "boxes": [
                        {
                            "xyxy": [axis[1] for axis in xyxy],
                            "precision": [axis[0] for axis in xyxy],
                            "conf": confidence,
                            "class_name": label,
                        }
                        for xyxy, confidence, label in boxes
                    ],
                }
            )
        docs.native.layout(json.dumps(rows), self.config.debug)
        docs.refresh()
        return docs


class ParagraphFinder:
    def __init__(self, config):
        self.config = config

    def process(self, docs):
        # Import model output as well, allowing explicit deterministic layout
        # adapters in regression tests without substituting the native parser.
        docs.sync()
        cfg = self.config
        docs.native.paragraphs(
            font_config(cfg.lang_out, cfg.primary_font_family),
            cfg.debug,
            cfg.split_short_lines,
            cfg.short_line_split_factor,
        )
        docs.refresh()


class StylesAndFormulas:
    def __init__(self, config):
        self.config = config

    def process(self, docs):
        cfg = self.config
        docs.native.styles(font_config(cfg.lang_out, cfg.primary_font_family))
        docs.refresh()


class Typesetting:
    def __init__(self, config):
        self.config = config

    def typesetting_document(self, docs):
        docs.sync()
        cfg = self.config
        docs.native.typeset(
            font_config(cfg.lang_out, cfg.primary_font_family), cfg.lang_out
        )
        docs.refresh()


class PDFCreater:
    def __init__(self, source, docs, config, mediabox):
        self.source, self.docs, self.config, self.mediabox = (
            source,
            docs,
            config,
            mediabox,
        )

    def write(self, config):
        import pymupdf

        self.docs.sync()
        raw = Path(config.get_working_file_path("native.pdf"))
        output = Path(config.get_working_file_path("native.mono.pdf"))
        self.docs.native.write(
            str(self.source),
            str(raw),
            font_config(config.lang_out, config.primary_font_family),
        )
        with pymupdf.open(raw) as pdf:
            for xref, boxes in self.mediabox.items():
                if xref < pdf.xref_length() and pdf.xref_get_key(xref, "Type")[1] in {
                    "/Page",
                    "/Pages",
                }:
                    for name, value in boxes.items():
                        pdf.xref_set_key(xref, name, value)
            # Restore original page objects before removing any of them. MuPDF
            # also repairs the page tree and destinations during selection.
            selected = [int(page.page_number) for page in self.docs.page]
            if selected != list(range(len(pdf))):
                pdf.select(selected)
            pdf.subset_fonts(fallback=False)
            pdf.save(output, garbage=1, deflate=True)
        return SimpleNamespace(no_watermark_mono_pdf_path=output, mono_pdf_path=output)
