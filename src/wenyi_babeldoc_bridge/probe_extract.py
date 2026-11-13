#!/usr/bin/env python3
"""Extract an explicitly supplied PDF through the production bridge pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

from wenyi_babeldoc_bridge.pipeline import ExtractSession, extract_to_session


def create_session(pdf: Path, pages: str | None, out: Path) -> ExtractSession:
    """Keep the source untouched and refuse to overwrite previous probe data."""
    pdf, out = pdf.expanduser().resolve(), out.expanduser().resolve()
    if not pdf.is_file():
        raise ValueError(f"PDF not found: {pdf}")
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError(f"Probe output directory must be empty: {out}")
    source = out / "source.pdf"
    shutil.copyfile(pdf, source)
    return extract_to_session(
        session_id=uuid.uuid4().hex, pdf_path=source, pages_spec=pages, out_dir=out
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--pages", help="1-based pages, for example 1,3-5")
    parser.add_argument(
        "--out", required=True, type=Path, help="Empty output directory"
    )
    args = parser.parse_args(argv)
    session = create_session(args.pdf, args.pages, args.out)
    print(
        json.dumps(
            {
                "session_id": session.session_id,
                "paragraph_count": len(session.paragraphs.paragraphs),
                "snapshot": str(session.snapshot_path),
                "paragraphs": str(session.out_dir / "paragraphs.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
