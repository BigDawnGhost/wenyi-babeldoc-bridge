#!/usr/bin/env python3
"""Exercise production extraction, frozen-session restore and PDF fillback.

Without --translations, preserve the original text (an identity round trip).
No translation provider is contacted. Use the HTTP smoke client to test transport.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from wenyi_babeldoc_bridge.pipeline import fillback_session, restore_session
from wenyi_babeldoc_bridge.probe_extract import create_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--pages", help="1-based pages, for example 1,3-5")
    parser.add_argument(
        "--out", required=True, type=Path, help="Empty output directory"
    )
    parser.add_argument(
        "--translations",
        type=Path,
        help="JSON mapping or object containing translations, annotations and rows",
    )
    args = parser.parse_args(argv)
    session = create_session(args.pdf, args.pages, args.out)
    payload = (
        json.loads(args.translations.read_text(encoding="utf-8"))
        if args.translations
        else {
            "translations": {
                unit.id: unit.source for unit in session.paragraphs.paragraphs
            },
            "rows": {
                unit.id: [
                    {
                        "target_start": row["source_start"],
                        "target_end": row["source_end"],
                    }
                    for row in unit.rows
                ]
                for unit in session.paragraphs.paragraphs
                if unit.rows
            },
        }
    )
    if not isinstance(payload, dict):
        raise ValueError("Translations must be a JSON object")
    if "translations" not in payload:
        payload = {"translations": payload}
    session = restore_session(session_id=session.session_id, out_dir=session.out_dir)
    output = fillback_session(
        session,
        payload["translations"],
        payload.get("annotations"),
        rows=payload.get("rows"),
    )
    print(
        json.dumps(
            {
                "paragraph_count": len(session.paragraphs.paragraphs),
                "output_pdf": str(output),
                "identity_round_trip": args.translations is None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
