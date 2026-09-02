"""v0 exchange schema for BabelDOC pre-extract → Wenyi → fillback."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "wenyi-babeldoc-paragraphs/v0"

# BabelDOC IL often parks layout-role tokens in ``unicode`` for non-body boxes.
_SKIP_UNICODE = frozenset(
    {
        "abandon",
        "title",
        "plain text",
        "plain_text",
        "fallback_line",
    }
)

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParagraphDocument:
    schema: str = SCHEMA_VERSION
    source_pdf: str = ""
    babeldoc_stage: str = "styles_and_formulas"
    pages_spec: str | None = None
    paragraphs: list[ParagraphUnit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_pdf": self.source_pdf,
            "babeldoc_stage": self.babeldoc_stage,
            "pages_spec": self.pages_spec,
            "paragraph_count": len(self.paragraphs),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
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
                )
            )
        doc = cls(
            schema=str(data.get("schema") or ""),
            source_pdf=str(data.get("source_pdf") or ""),
            babeldoc_stage=str(data.get("babeldoc_stage") or ""),
            pages_spec=data.get("pages_spec"),
            paragraphs=units,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_pdf": self.source_pdf,
            "translation_count": len(self.translations),
            "translations": self.translations,
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
    if not text:
        return False
    stripped = text.strip()
    if not stripped or stripped in _SKIP_UNICODE:
        return False
    if len(stripped) < 8:
        return False
    if stripped.startswith("/Volume/") or "wea25324_fm" in stripped:
        return False
    return True


def paragraph_from_il(
    *,
    page_number: int,
    index: int,
    raw: dict[str, Any],
) -> ParagraphUnit | None:
    source = str(raw.get("unicode") or "")
    if not is_translatable_unicode(source):
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
        page = para.get("page")
        index = para.get("index")
        if not isinstance(page, int) or not isinstance(index, int):
            errors.append(f"{pid}: page/index must be int")
        elif make_paragraph_id(page, index) != pid:
            errors.append(f"{pid}: id mismatch page/index")
    return errors


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
