"""Synthetic IL documents for parser and session snapshot tests."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field, fields


@dataclass
class _FakeStyleRun:
    debug_info: bool = False
    unicode: str = "plain text"


@dataclass
class _FakeComposition:
    pdf_same_style_unicode_characters: _FakeStyleRun | None = None


@dataclass
class _FakeParagraph:
    unicode: str
    pdf_paragraph_composition: list[object] = field(default_factory=list)
    vertical: bool = False


@dataclass
class _FakePage:
    page_number: int
    pdf_paragraph: list[_FakeParagraph] = field(default_factory=list)
    pdf_rectangle: list[object] = field(default_factory=list)


@dataclass
class _FakeDocument:
    page: list[_FakePage] = field(default_factory=list)

    @property
    def document(self):
        return self

    def snapshot(self):
        return json.dumps(
            self,
            default=lambda obj: {
                "fake_type": type(obj).__name__,
                "values": {
                    field.name: getattr(obj, field.name) for field in fields(obj)
                },
            },
        )

    def write_checkpoint(self, path):
        data = gzip.compress(self.snapshot().encode("utf-8"), mtime=0)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def restore_checkpoint(cls, path, sha256):
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise RuntimeError("session IL snapshot checksum mismatch")
        return cls.restore(gzip.decompress(data).decode("utf-8"))

    @staticmethod
    def restore(text):
        classes = {
            cls.__name__: cls
            for cls in (
                _FakeDocument,
                _FakePage,
                _FakeParagraph,
                _FakeComposition,
                _FakeStyleRun,
            )
        }
        return json.loads(
            text,
            object_hook=lambda obj: (
                classes[obj["fake_type"]](**obj["values"])
                if "fake_type" in obj
                else obj
            ),
        )
