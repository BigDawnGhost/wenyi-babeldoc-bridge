#!/usr/bin/env python3
"""Smoke-test the local bridge: extract → fake translations → fillback."""

from __future__ import annotations

import argparse
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

    translations = {
        p["id"]: f"[假回填{i + 1}]{p['source'][:80]}" for i, p in enumerate(paragraphs)
    }
    body = json.dumps(
        {"session_id": session_id, "translations": translations}, ensure_ascii=False
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
