"""Spawn-safe PDF tasks: importing a worker must not initialize BabelDOC services."""

from __future__ import annotations


def subset_fonts(pdf_path: str, output_path: str) -> None:
    import pymupdf

    with pymupdf.open(pdf_path) as document:
        document.subset_fonts(fallback=False)
        document.save(output_path)


def save_clean(
    pdf_path: str,
    output_path: str,
    garbage: int = 1,
    deflate: bool = True,
    clean: bool = True,
    deflate_fonts: bool = True,
    linear: bool = False,
) -> None:
    import pymupdf

    with pymupdf.open(pdf_path) as document:
        document.save(
            output_path,
            garbage=garbage,
            deflate=deflate,
            clean=clean,
            deflate_fonts=deflate_fonts,
            linear=linear,
        )
