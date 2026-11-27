"""Offline extraction and fillback check against the annotated, original PDFs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pymupdf
from samples.fetch_samples import matches

from wenyi_babeldoc_bridge.pipeline import fillback_session, restore_session_with_docs
from wenyi_babeldoc_bridge.probe_extract import create_session

SAMPLES = Path(__file__).with_name("samples")
# Right edges measured on the originals, independent of the recognizer.
EDGES = {"uk-treasury-guidance.pdf": 469, "nist-fips180.pdf": 540, "nasa-sti.pdf": 540}


def block_network(event, _args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("Network disabled for the TOC probe")


def compact(text):
    return re.sub(r"\.{3,}", "", "".join(unicodedata.normalize("NFKC", text).split()))


def title_counts(page, labels, units, first_wrap):
    # Ground truth for these annotated single-column pages: each printed label
    # ends an entry. The first NASA title also uses the preceding visual line.
    words = page.get_text("words")
    previous = labels[0][1] - (18 if first_wrap else 2)
    actual = [
        (compact(s), pymupdf.Rect(box) * page.transformation_matrix)
        for u in units
        if u.page == page.number
        for s, box in (
            [(u.source[r["source_start"] : r["source_end"]], r["box"]) for r in u.rows]
            or [(u.source, u.box)]
        )
        if box
    ]
    exact = 0
    for label in labels:
        group = [
            w for w in words if previous <= (w[1] + w[3]) / 2 <= label[3] and w != label
        ]
        # Group the different font sizes on one baseline before sorting by x.
        lines = []
        for w in sorted(group, key=lambda w: w[3]):
            if not lines or w[3] - lines[-1][0][3] > 2:
                lines.append([])
            lines[-1].append(w)
        task = compact(
            "".join(w[4] for line in lines for w in sorted(line, key=lambda w: w[0]))
        )
        y = (label[1] + label[3]) / 2
        exact += (
            sum(s == task and rect.y0 - 2 <= y <= rect.y1 + 2 for s, rect in actual)
            == 1
        )
        previous = label[3] + 0.1
    return exact


def control_units(document, pages):
    return [
        {k: v for k, v in u.to_dict(for_client=True).items() if k != "debug_id"}
        for u in document.paragraphs
        if u.page + 1 in pages
    ]


def check(path, pages, edge, *, read_only=False, require_all=False):
    with tempfile.TemporaryDirectory() as tmp, pymupdf.open(path) as original:
        spec = ",".join(map(str, pages))
        session = create_session(path, spec, Path(tmp))
        units = session.paragraphs.paragraphs
        for n in pages:
            signatures = [
                (u.index, u.source, u.box, u.rows) for u in units if u.page == n - 1
            ]
            digest = hashlib.sha256(json.dumps(signatures).encode()).hexdigest()[:12]
            print(f"{path.name} p{n}: {len(signatures)} units; signature {digest}")
        unchanged = [n for n in pages if read_only or pages[n] == 0]
        if require_all and unchanged:
            # Compare the actual export with just this repair disabled, using
            # the same engine and model. Debug IDs are random across extracts.
            with patch(
                "wenyi_babeldoc_bridge.preservation.toc.front_toc", return_value={}
            ):
                control = create_session(path, spec, Path(tmp) / "control")
            if control_units(session.paragraphs, unchanged) != control_units(
                control.paragraphs, unchanged
            ):
                raise ValueError(
                    f"Repair changed a control page: {path.name} {unchanged}"
                )
            print(f"  Unchanged vs repair disabled: physical pages {unchanged}")
        if read_only:
            return
        session, docs = restore_session_with_docs(
            session_id=session.session_id, out_dir=session.out_dir
        )
        # Replace editable prose (including any erroneously exported page labels).
        # Reuse identity alignment for protected objects and structured rows.
        translations = {
            u.id: u.source
            if u.rows or any(a.get("protected") for a in u.annotations)
            else "译文示例"
            for u in units
        }
        rows = {
            u.id: [
                {"target_start": r["source_start"], "target_end": r["source_end"]}
                for r in u.rows
            ]
            for u in units
            if u.rows
        }
        out = fillback_session(session, translations, rows=rows, _pristine_docs=docs)
        with pymupdf.open(out) as rendered:
            for index, (physical, expected) in enumerate(pages.items()):
                if not expected:
                    continue
                if edge is None:
                    raise ValueError(f"No annotated page-number column: {path.name}")
                labels = sorted(
                    (
                        w
                        for w in original[physical - 1].get_text("words")
                        if w[4].isdecimal() and abs(w[2] - edge) < 2
                    ),
                    key=lambda w: w[1],
                )
                if len(labels) != expected:
                    raise ValueError(
                        f"{path.name} p{physical}: expected {expected} source labels, found {len(labels)}"
                    )
                titles = title_counts(
                    original[physical - 1], labels, units, path.name == "nasa-sti.pdf"
                )
                print(
                    f"  p{physical}: {titles}/{expected} independently editable complete titles (label excluded)"
                )

                # Compare individual glyph origins rather than PDF word grouping:
                # the writer may place a standalone number before its title.
                def digits(page):
                    return Counter(
                        (ch["c"], round(ch["origin"][0], 1), round(ch["origin"][1], 1))
                        for b in page.get_text(
                            "rawdict",
                            flags=pymupdf.TEXTFLAGS_RAWDICT
                            & ~pymupdf.TEXT_PRESERVE_IMAGES,
                        )["blocks"]
                        for line in b.get("lines", [])
                        for span in line["spans"]
                        for ch in span["chars"]
                        if ch["c"].isdecimal()
                    )

                source, target = digits(original[physical - 1]), digits(rendered[index])
                good = 0
                for x0, y0, x1, y1, value, *_ in labels:
                    required = {
                        k: v
                        for k, v in source.items()
                        if x0 - 0.1 <= k[1] < x1 and y0 <= k[2] <= y1
                    }
                    if sum(required.values()) != len(value):
                        raise ValueError(
                            f"Ambiguous source glyphs: {path.name} p{physical}"
                        )
                    good += all(target[k] == v for k, v in required.items())
                print(
                    f"  p{physical}: {good}/{expected} printed labels at original origins"
                )
                if require_all and not titles == good == expected:
                    raise ValueError(
                        f"Incomplete titles or moved labels: {path.name} p{physical}"
                    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper", type=Path, help="Optional authorized GRH sample")
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Fail if any expected title or page label is missing",
    )
    args = parser.parse_args()
    sys.addaudithook(block_network)
    for sample in json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8")):
        name = sample["file"]
        path = SAMPLES / ".cache" / name
        if not matches(path, sample["bytes"], sample["sha256"]):
            raise ValueError(f"Missing or mismatched public sample: {name}")
        pages = dict(
            sorted(
                (p["physical_page"], p["toc_entries"]) for p in sample["probe_pages"]
            )
        )
        check(
            path,
            pages,
            EDGES.get(name),
            read_only=name == "rfc9000.pdf",
            require_all=args.require_all,
        )
    if args.paper:
        check(args.paper, {1: 22, 2: 47, 3: 40}, 485, require_all=args.require_all)


if __name__ == "__main__":
    main()
