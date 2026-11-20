"""Differential coverage for the native annotation range planners."""

from __future__ import annotations

import random
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from wenyi_babeldoc_bridge.annotations import _skip_conflicts
from wenyi_babeldoc_bridge.rows import inject_rows, partition_row_annotations


def item(item_id, kind, start, end, **fields):
    return dict(id=item_id, kind=kind, source_start=start, source_end=end, **fields)


def placement(item_id, start, end):
    return dict(id=item_id, target_start=start, target_end=end)


def source_row(start, end):
    return dict(source_start=start, source_end=end, box=[0, start, 100, start + 1])


def target_row(start: int, end: int) -> dict[str, int]:
    return dict(target_start=start, target_end=end)


def reference_conflicts(entries, skipped):
    for i, (kind, start, end, style, linked) in enumerate(entries):
        for j in range(i + 1, len(entries)):
            other_kind, left, right, other_style, other_linked = entries[j]
            if other_kind != kind or kind == "link":
                continue
            overlaps = max(start, left) < min(end, right)
            if kind == "formula":
                overlaps |= start == end and left < start < right
                overlaps |= left == right and start < left < end
            else:
                overlaps &= style != other_style
                if linked and not other_linked and left <= start <= end <= right:
                    overlaps = False
                if other_linked and not linked and start <= left <= right <= end:
                    overlaps = False
            if overlaps:
                skipped[str(i)] = skipped[str(j)] = f"conflicting_{kind}s"


def reference_partition(items, rows):
    result = []
    for value in items:
        start, end = value["source_start"], value["source_end"]
        parts = []
        for i, row in enumerate(rows):
            left, right = row["source_start"], row["source_end"]
            if start == end and left <= start <= right:
                parts.append((i, start, end))
            elif start < right and left < end:
                parts.append((i, max(start, left), min(end, right)))
        if value["kind"] == "formula" and (
            len(parts) != 1 or parts[0][1:] != (start, end)
        ):
            raise ValueError("A formula crosses structured rows")
        for i, left, right in parts:
            item_id = f"{value['id']}:row:{i}" if len(parts) > 1 else value["id"]
            result.append(dict(value, id=item_id, source_start=left, source_end=right))
    return result


def reference_row_plans(rows, targets, items, placements):
    by_id = {row["id"]: row for row in placements}
    result, skipped = [], {}
    for row, target in zip(rows, targets):
        members, local = [], []
        start, end = target["target_start"], target["target_end"]
        for value in items:
            if not (
                row["source_start"] <= value["source_start"]
                and value["source_end"] <= row["source_end"]
            ):
                continue
            members.append(value)
            current = by_id.get(value["id"])
            if current is None:
                continue
            left, right = current["target_start"], current["target_end"]
            if not start <= left <= right <= end:
                skipped[value["id"]] = "cross_row_alignment"
            else:
                local.append(
                    dict(current, target_start=left - start, target_end=right - start)
                )
        result.append((members, local))
    return result, skipped


class AnnotationRangeTests(unittest.TestCase):
    def assert_conflict_parity(self, entries):
        items, placements, compositions, linked_styles = [], {}, [], set()
        for i, (kind, start, end, style, linked) in enumerate(entries):
            items.append(item(str(i), kind, start, end, composition_index=i))
            placements[str(i)] = placement(str(i), start, end)
            compositions.append(
                NS(pdf_same_style_characters=NS(pdf_style=NS(font_size=style)))
            )
            if linked:
                linked_styles.add(str(i))
        expected = {"4": "existing_skip", "unrelated": "missing_placement"}
        actual = dict(expected)
        reference_conflicts(entries, expected)
        _skip_conflicts(
            NS(pdf_paragraph_composition=compositions),
            items,
            placements,
            actual,
            linked_styles,
        )
        self.assertEqual(list(actual.items()), list(expected.items()))

    def test_conflicts_match_reference_for_sparse_and_dense_ranges(self):
        self.assert_conflict_parity(
            [
                ("formula", 10, 20, None, False),
                ("style", 1, 6, 10, False),
                ("formula", 20, 20, None, False),  # Exclusive formula end.
                ("formula", 10, 10, None, False),  # Exclusive formula start.
                ("formula", 12, 12, None, False),  # Strict interior.
                ("style", 2, 5, 10, False),  # Equal value, distinct IL style.
                ("style", 1, 6, 11, True),  # Link evidence also with equal bounds.
                ("style", 4, 7, 11, True),  # Partial overlap with prose.
                ("style", 2, 5, 12, True),  # Link evidence cannot break this tie.
                ("link", 10, 20, None, False),
                ("formula", 20, 20, None, False),  # Coincident points do not conflict.
                ("style", 20, 30, 10, False),  # Contains the next link-backed style.
                ("style", 21, 24, 12, True),
            ]
        )
        rng = random.Random(2718)
        for stride in (1, 100):
            for _ in range(25):
                entries = []
                for i in range(48):
                    start = (i // 3) * stride + rng.randrange(3)
                    kind = rng.choice(("style", "formula", "link"))
                    width = rng.randrange(8) if kind != "style" else rng.randrange(1, 8)
                    entries.append(
                        (
                            kind,
                            start,
                            start + width,
                            rng.randrange(3),
                            rng.choice((0, 1)),
                        )
                    )
                rng.shuffle(entries)
                self.assert_conflict_parity(entries)

    def test_partitions_match_reference_in_annotation_and_row_order(self):
        rows = [source_row(left, right) for left, right in [(0, 3), (3, 6), (8, 12)]]
        rng = random.Random(314)
        link = object()
        for structure in (rows, rows[::-1], [], [source_row(0, 100)]):
            items = [
                item("wide", "style", 1, 11, composition_index=3),
                item("shared", "link", 3, 3, link_id=link),
            ]
            for i in range(32):
                left = rng.randrange(14)
                items.append(item(str(i), "link", left, rng.randrange(left, 15)))
            actual = partition_row_annotations(items, structure)
            self.assertEqual(actual, reference_partition(items, structure))
            for part in (value for value in actual if value["id"].startswith("shared")):
                self.assertIs(part["link_id"], link)
        for start, end in ((0, 0), (3, 3), (12, 12), (2, 4), (6, 8), (9, 13)):
            items = [item("formula", "formula", start, end)]
            try:
                expected = reference_partition(items, rows)
            except ValueError as error:
                with self.assertRaisesRegex(ValueError, str(error)):
                    partition_row_annotations(items, rows)
            else:
                self.assertEqual(partition_row_annotations(items, rows), expected)

    def test_injection_plans_match_reference_and_keep_annotation_identity(self):
        rows = [source_row(left, right) for left, right in [(0, 4), (4, 7), (9, 12)]]
        targets = [target_row(a, b) for a, b in ((0, 3), (3, 9), (10, 15))]
        items = [
            item("last", "style", 9, 11),
            item("edge", "formula", 4, 4),
            item("outside", "link", 1, 3),
            item("missing", "link", 4, 7),
            item("first", "link", 0, 4),
            item("unowned", "style", 5, 10),
        ]
        placements = [
            placement("last", 10, 12),
            placement("edge", 3, 3),
            placement("outside", 2, 4),
            placement("first", 10, 11),  # Last placement for an ID wins.
            dict(placement("first", 1, 2), status="aligned"),
            placement("unowned", 9, 10),
        ]
        expected, expected_skips = reference_row_plans(rows, targets, items, placements)
        para = NS(box=NS(x=0, y=0, x2=100, y2=100))
        skipped = {}
        with patch(
            "wenyi_babeldoc_bridge.rows.inject_aligned_translation", return_value=[]
        ):
            paragraphs, plans = inject_rows(
                {},
                para,
                NS(rows=rows, annotations=items),
                "123456789 12345",
                targets,
                placements,
                skipped,
            )
        self.assertEqual([p.box.y for p in paragraphs], [0, 4, 9])
        self.assertEqual(list(skipped.items()), list(expected_skips.items()))
        for (_, _, actual_members, actual_placements), (members, local) in zip(
            plans, expected
        ):
            self.assertEqual(actual_members, members)
            self.assertEqual(actual_placements, local)
            for actual, original in zip(actual_members, members):
                self.assertIs(actual, original)

    def test_protected_cross_row_failure_does_not_apply_later_skips(self):
        rows = [source_row(0, 4), source_row(4, 8)]
        targets = [target_row(0, 4), target_row(4, 8)]
        items = [
            item("required", "formula", 2, 2, protected=True),
            item("later", "style", 4, 6),
        ]
        placements = [placement("required", 5, 5), placement("later", 0, 1)]
        skipped = {}
        with self.assertRaisesRegex(
            ValueError, "Cannot restore protected PDF objects: required"
        ):
            inject_rows(
                {},
                NS(box=NS()),
                NS(rows=rows, annotations=items),
                "ABCDEFGH",
                targets,
                placements,
                skipped,
            )
        self.assertEqual(skipped, {"required": "cross_row_alignment"})
