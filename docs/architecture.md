# Where a layout rule belongs

[简体中文](zh/architecture.md) · [Development setup and tests](installation.md#validation) · [HTTP contract](api.md)

The bridge is one PDF engine behind an HTTP boundary. A contents entry, a
figure legend and an ordinary paragraph use the same extraction checkpoint
and writer. Put a rule at the stage that owns the thing it changes, rather
than adding a second pipeline for a particular kind of document.

| Stage | Owner (under `src/wenyi_babeldoc_bridge/`) | What it can change |
| --- | --- | --- |
| Before paragraph finding | `preservation/layout.py`, called by `native.LayoutParser` | Model detection boxes. Read original PDF evidence and native glyphs; do not edit their text, allocate paragraph IDs or create translation units. |
| After paragraph finding | `rows.py`, `lists.py`, `annotations.py`, `protected_objects.py` and the math policies, coordinated by `pipeline.py` | Capture row boundaries, fixed glyphs, annotations and their offsets against the original paragraph identities. Do not rerun page segmentation. |
| Fillback | `pipeline.fillback_session`, the row/annotation injectors and the native typesetter/writer | Apply validated translations to a fresh copy of the frozen graph. Restore links using the selected output pages. Do not redetect the contents section or load a layout model during recovery. |

## Before paragraph finding

`native.py` runs the model and transfers detections to the native engine.
`preservation/layout.py` owns the repair order: first apply `boxes.py`'s
local repairs (clipped words, captions and accents), then allow `toc.py` to
separate a confirmed title and its printed page number. Both rules use
`geometry.py` for model-space rectangles, native padding and overlap. They
do not call each other. If TOC evidence or coordinate agreement is missing,
keep the ordinary repaired boxes; do not undo the earlier repair.

For example, the TOC rule checks the original digit glyphs before giving them
a number box. They need no translation or fillback placeholder. This is not
the `rows` protocol: it makes a title available to native paragraph finding,
whereas `rows` marks items *inside an existing paragraph*. Keep the [contents
eligibility and client-visible behavior](api.md#structured-item-rows) in the
API contract.

## Regression checks

- Keep automated tests and their helpers in `tests/`, outside the installed
  package. Keep manual experiments and optional public sample data acquisition
  in `scripts/`; neither is a runtime dependency.
- Test both a match and a plausible non-match. For overlapping rules, use a
  page with competing regions and check that unrelated content is unchanged.
  In a behavior-preserving refactor, compare the pre- and post-change output,
  not just the number of recognized entries.
- If a rule affects glyph ownership, exercise extraction, snapshot recovery
  and fillback. Check stable paragraph IDs, editable text and geometry; in the
  rendered PDF check the original glyph positions and in-range link targets.
  The [sample probe](../scripts/toc_layout_probe/README.md) is an opt-in check;
  default tests do not fetch PDFs or call a translation service.
