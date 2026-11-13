"""v0 exchange schema for BabelDOC pre-extract → Wenyi → fillback."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "wenyi-babeldoc-paragraphs/v0"

_PLACEHOLDER_RE = re.compile(
    r"\{v\d+\}|<style\s+id\s*=\s*'?\d+'?\s*>|</style>",
    re.IGNORECASE,
)


@dataclass
class ParagraphUnit:
    """One BabelDOC paragraph exposed to Wenyi."""

    id: str
    page: int
    index: int
    source: str
    debug_id: str | None = None
    layout_label: str | None = None
    layout_id: int | None = None
    box: list[float] | None = None
    has_placeholders: bool = False
    annotations: list[dict[str, Any]] = field(default_factory=list)
    original_source: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParagraphDocument:
    schema: str = SCHEMA_VERSION
    source_pdf: str = ""
    babeldoc_stage: str = "styles_and_formulas"
    pages_spec: str | None = None
    paragraphs: list[ParagraphUnit] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_pdf": self.source_pdf,
            "babeldoc_stage": self.babeldoc_stage,
            "pages_spec": self.pages_spec,
            "paragraph_count": len(self.paragraphs),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "links": self.links,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParagraphDocument:
        """Restore a validated paragraph document from its JSON representation."""
        paragraphs = data.get("paragraphs")
        if not isinstance(paragraphs, list):
            raise ValueError("paragraphs must be a list")
        units: list[ParagraphUnit] = []
        for raw in paragraphs:
            if not isinstance(raw, dict):
                raise ValueError("paragraph entry must be an object")
            units.append(
                ParagraphUnit(
                    id=raw.get("id"),
                    page=raw.get("page"),
                    index=raw.get("index"),
                    source=raw.get("source"),
                    debug_id=raw.get("debug_id"),
                    layout_label=raw.get("layout_label"),
                    layout_id=raw.get("layout_id"),
                    box=raw.get("box"),
                    has_placeholders=bool(raw.get("has_placeholders", False)),
                    annotations=raw.get("annotations", []),
                    original_source=raw.get("original_source"),
                    rows=raw.get("rows", []),
                )
            )
        doc = cls(
            schema=str(data.get("schema") or ""),
            source_pdf=str(data.get("source_pdf") or ""),
            babeldoc_stage=str(data.get("babeldoc_stage") or ""),
            pages_spec=data.get("pages_spec"),
            paragraphs=units,
            links=data.get("links", []),
        )
        errors = validate_paragraph_document(doc)
        if errors:
            raise ValueError("paragraph document invalid: " + "; ".join(errors))
        return doc

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    @classmethod
    def read_json(cls, path: str | Path) -> ParagraphDocument:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("paragraph document must be an object")
        return cls.from_dict(data)


@dataclass
class TranslationDocument:
    schema: str = "wenyi-babeldoc-translations/v0"
    source_pdf: str = ""
    translations: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, dict[str, Any]] = field(default_factory=dict)
    rows: dict[str, list[dict[str, int]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_pdf": self.source_pdf,
            "translation_count": len(self.translations),
            "translations": self.translations,
            "annotations": self.annotations,
            "rows": self.rows,
        }

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


def make_paragraph_id(page: int, index: int) -> str:
    return f"{page}:{index}"


def is_translatable_unicode(text: str | None) -> bool:
    """Keep all nonempty text regardless of its length or content."""
    return bool(text and text.strip())


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def is_debug_overlay_paragraph(para: Any) -> bool:
    """Identify debug labels in either serialized IL or BabelDOC objects."""
    for composition in _field(para, "pdf_paragraph_composition") or []:
        style_run = _field(composition, "pdf_same_style_unicode_characters")
        if _field(style_run, "debug_info"):
            return True
    return False


def is_translatable_paragraph(para: Any) -> bool:
    """Match BabelDOC's vertical-text protection before exporting or injecting text."""
    return (
        not _field(para, "vertical")
        and not is_debug_overlay_paragraph(para)
        and is_translatable_unicode(_field(para, "unicode"))
    )


def paragraph_from_il(
    *,
    page_number: int,
    index: int,
    raw: dict[str, Any],
) -> ParagraphUnit | None:
    source = str(raw.get("unicode") or "")
    if not is_translatable_paragraph(raw):
        return None
    box = raw.get("box")
    box_list: list[float] | None = None
    if isinstance(box, dict) and all(k in box for k in ("x", "y", "x2", "y2")):
        box_list = [
            float(box["x"]),
            float(box["y"]),
            float(box["x2"]),
            float(box["y2"]),
        ]
    debug_id = raw.get("debug_id")
    layout_id = raw.get("layout_id")
    return ParagraphUnit(
        id=make_paragraph_id(page_number, index),
        page=int(page_number),
        index=int(index),
        source=source,
        debug_id=str(debug_id) if debug_id else None,
        layout_label=raw.get("layout_label"),
        layout_id=int(layout_id) if isinstance(layout_id, int) else None,
        box=box_list,
        has_placeholders=bool(_PLACEHOLDER_RE.search(source)),
    )


def load_paragraphs_from_styles_json(
    styles_path: str | Path,
    *,
    source_pdf: str = "",
    pages_spec: str | None = None,
) -> ParagraphDocument:
    payload = json.loads(Path(styles_path).read_text(encoding="utf-8"))
    pages = payload.get("page") or []
    units: list[ParagraphUnit] = []
    for page in pages:
        page_number = int(page.get("page_number", 0))
        for index, raw in enumerate(page.get("pdf_paragraph") or []):
            if not isinstance(raw, dict):
                continue
            unit = paragraph_from_il(page_number=page_number, index=index, raw=raw)
            if unit is not None:
                units.append(unit)
    return ParagraphDocument(
        source_pdf=source_pdf,
        pages_spec=pages_spec,
        paragraphs=units,
    )


def validate_paragraph_document(doc: ParagraphDocument | dict[str, Any]) -> list[str]:
    errors: list[str] = []
    data = doc.to_dict() if isinstance(doc, ParagraphDocument) else doc
    if data.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {data.get('schema')!r}")
    paragraphs = data.get("paragraphs") or []
    seen: set[str] = set()
    for i, para in enumerate(paragraphs):
        pid = para.get("id")
        if not isinstance(pid, str) or not pid:
            errors.append(f"paragraphs[{i}]: missing id")
            continue
        if pid in seen:
            errors.append(f"duplicate id: {pid}")
        seen.add(pid)
        source = para.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"{pid}: empty source")
        rows = para.get("rows", [])
        if not isinstance(rows, list):
            errors.append(f"{pid}: rows must be a list")
        elif rows and isinstance(source, str):
            errors.extend(
                f"{pid}: {error}" for error in row_range_errors(source, rows, "source")
            )
            if len(rows) < 2:
                errors.append(f"{pid}: structured directories require multiple rows")
            for row in rows:
                box = row.get("box") if isinstance(row, dict) else None
                if (
                    not isinstance(box, list)
                    or len(box) != 4
                    or any(
                        type(v) not in (int, float) or not math.isfinite(v) for v in box
                    )
                    or box[0] >= box[2]
                    or box[1] >= box[3]
                ):
                    errors.append(f"{pid}: invalid row box")
        annotations = para.get("annotations", [])
        if not isinstance(annotations, list):
            errors.append(f"{pid}: annotations must be a list")
            continue
        annotation_ids: set[str] = set()
        for item in annotations:
            if not isinstance(item, dict):
                errors.append(f"{pid}: invalid annotation")
                continue
            item_id = item.get("id")
            start, end = item.get("source_start"), item.get("source_end")
            if (
                not isinstance(item_id, str)
                or not item_id
                or item_id in annotation_ids
                or item.get("kind") not in {"formula", "style", "link"}
                or item.get("mode") not in {"point", "range"}
                or type(start) is not int
                or type(end) is not int
                or not isinstance(source, str)
                or not 0 <= start <= end <= len(source)
                or (item["mode"] == "point") != (start == end)
            ):
                errors.append(f"{pid}: invalid annotation range or identity")
            elif item["kind"] in {"formula", "style"} and (
                type(item.get("composition_index")) is not int
                or item["composition_index"] < 0
            ):
                errors.append(f"{pid}: invalid annotation composition")
            elif item["kind"] == "link" and not isinstance(item.get("link_id"), str):
                errors.append(f"{pid}: invalid link identity")
            if isinstance(item_id, str):
                annotation_ids.add(item_id)
        page = para.get("page")
        index = para.get("index")
        if not isinstance(page, int) or not isinstance(index, int):
            errors.append(f"{pid}: page/index must be int")
        elif make_paragraph_id(page, index) != pid:
            errors.append(f"{pid}: id mismatch page/index")
    return errors


def row_range_errors(text: str, rows: Any, prefix: str) -> list[str]:
    """Require ordered nonempty ranges covering all non-whitespace text."""
    if not isinstance(rows, list) or not rows:
        return ["row ranges must be a nonempty list"]
    cursor = 0
    for row in rows:
        if not isinstance(row, dict):
            return ["invalid row range"]
        start, end = row.get(f"{prefix}_start"), row.get(f"{prefix}_end")
        if (
            type(start) is not int
            or type(end) is not int
            or not cursor <= start < end <= len(text)
            or text[cursor:start].strip()
            or not text[start:end].strip()
        ):
            return ["invalid or incomplete row ranges"]
        cursor = end
    return ["uncovered text after final row"] if text[cursor:].strip() else []


def validate_translations_against_paragraphs(
    paragraphs: ParagraphDocument | dict[str, Any],
    translations: TranslationDocument | dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    pdata = (
        paragraphs.to_dict()
        if isinstance(paragraphs, ParagraphDocument)
        else paragraphs
    )
    tdata = (
        translations.to_dict()
        if isinstance(translations, TranslationDocument)
        else translations
    )
    ids = {p["id"] for p in (pdata.get("paragraphs") or []) if isinstance(p, dict)}
    mapping = tdata.get("translations") or {}
    if not isinstance(mapping, dict):
        return ["translations must be an object"]
    for pid, text in mapping.items():
        if pid not in ids:
            errors.append(f"unknown translation id: {pid}")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"empty translation for {pid}")
    missing = sorted(ids - set(mapping))
    if missing:
        errors.append(
            f"missing translations for {len(missing)} ids (e.g. {missing[:3]})"
        )
    return errors
