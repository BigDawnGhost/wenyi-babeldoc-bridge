#!/usr/bin/env python3
"""Smoke-test the local bridge: extract → fake translations → fillback."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def _post_multipart(url: str, pdf: Path, pages: str | None) -> dict:
    boundary = "----wenyiBoundary7MA4YWxkTrZu0gW"
    body = bytearray()
    filename = pdf.name

    def add(
        name: str, value: bytes, filename: str | None = None, ctype: str | None = None
    ):
        body.extend(f"--{boundary}\r\n".encode())
        if filename is None:
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            )
            body.extend(value)
            body.extend(b"\r\n")
        else:
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {ctype or 'application/pdf'}\r\n\r\n"
                ).encode()
            )
            body.extend(value)
            body.extend(b"\r\n")

    add("file", pdf.read_bytes(), filename=filename)
    if pages:
        add("pages", pages.encode())
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--pages", default="15")
    parser.add_argument(
        "--out", type=Path, default=Path("/tmp/wenyi_babeldoc_bridge_smoke.pdf")
    )
    args = parser.parse_args()

    health = urllib.request.urlopen(args.base + "/health", timeout=10).read()
    print("health", health.decode())

    print("extract...")
    payload = _post_multipart(args.base + "/extract", args.pdf, args.pages)
    session_id = payload["session_id"]
    paragraphs = payload["paragraphs"]["paragraphs"]
    print("session", session_id, "paragraphs", len(paragraphs))

    translations, annotations, rows = {}, {}, {}
    for i, paragraph in enumerate(paragraphs):
        # Identity text makes a deterministic layout smoke test, not a model-quality test.
        # Keep full annotated source and send exact offsets; never truncate a formula.
        items = paragraph.get("annotations") or []
        text = (
            paragraph["source"]
            if items or paragraph.get("rows")
            else f"[假回填{i + 1}]{paragraph['source'][:80]}"
        )
        translations[paragraph["id"]] = text
        if paragraph.get("rows"):
            rows[paragraph["id"]] = [
                {"target_start": row["source_start"], "target_end": row["source_end"]}
                for row in paragraph["rows"]
            ]
        if items:
            annotations[paragraph["id"]] = {
                "target_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "placements": [
                    {
                        "id": item["id"],
                        "mode": item["mode"],
                        "target_start": item["source_start"],
                        "target_end": item["source_end"],
                        "target_order": order,
                        "status": "aligned",
                    }
                    for order, item in enumerate(items)
                ],
            }
    body = json.dumps(
        {
            "session_id": session_id,
            "translations": translations,
            "annotations": annotations,
            "rows": rows,
        },
        ensure_ascii=False,
    ).encode()
    print("fillback...")
    req = urllib.request.Request(
        args.base + "/fillback",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        pdf_bytes = resp.read()
        statistics = resp.headers.get("X-Wenyi-PDF-Annotation-Stats")
    if statistics:
        print("annotations", json.dumps(json.loads(statistics), sort_keys=True))
    args.out.write_bytes(pdf_bytes)
    print("wrote", args.out, "bytes", len(pdf_bytes))

    # cleanup
    del_req = urllib.request.Request(
        args.base + f"/session/{session_id}", method="DELETE"
    )
    with urllib.request.urlopen(del_req, timeout=30) as resp:
        print("deleted", resp.read().decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
