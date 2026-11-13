# HTTP API and sessions

[简体中文](zh/api.md) · [Overview](../README.md) · [Installation](installation.md)

## Endpoints

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/extract` | Multipart PDF in `file`, optional `pages`; returns `session_id` and `paragraphs` |
| POST | `/fillback` | JSON `{session_id, translations: {id: text}, annotations?: {id: alignment}, rows?: {id: ranges}}`; returns a monolingual PDF |
| GET / DELETE | `/session/{id}` | Inspect or release a session |

Wenyi generates translations. The bridge extracts paragraphs and fills them back
using BabelDOC; it does not run a whole-book translation frontend.
The Desktop plugin adds a private authenticated boundary around the same HTTP
contract; see the [runtime protocol](desktop.md#runtime-protocol).

## Paragraph identity

Paragraph IDs are `"{page}:{index}"`, where `index` is the original paragraph
position in the page IL. Filtering must not renumber those positions.
Extraction and fillback use the same identity rules.

Extraction preserves all nonempty source text, including short words, single
characters, numeric text, and real text equal to layout class names such as
`table` or `title`, except paragraphs marked `vertical=True` by BabelDOC.
Vertical/rotated paragraphs are not exported for translation; their original
glyphs, fonts, sizes, coordinates and rotation remain in the frozen IL and pass
through fillback without reflow, regardless of layout class or text content.
Debug overlays identified by IL `debug_info` are also excluded. There is no
length- or text-content-based filter for the remaining paragraphs.

Older sessions may still contain exported vertical paragraph IDs. Requests must
continue to cover those IDs, but fillback ignores their supplied text, annotation
placements and row ranges, restoring their original glyphs and links instead.
Session recovery does not rewrite the saved paragraph list or renumber IDs.
Nonvertical paragraphs use normal text/annotation fillback even when their
translations equal the extracted source; text equality is not a passthrough rule.

After updating and restarting a bridge that previously filtered such text,
extract affected PDFs again. Existing sessions are not migrated or supplemented
automatically.

## Directory rows

`/health` advertises `toc-rows-v1`. Confidently detected aligned, numbered sibling
contents entries with dot leaders and page numbers have a nonempty `rows` list.
Each row contains half-open `source_start` / `source_end` offsets and its original
PDF-coordinate `box: [x, y, x2, y2]`. These boundaries are captured before style
grouping merges visual lines. Ordinary prose wrapping remains soft; ambiguous
layouts remain ordinary paragraphs.

Rows are children of the original paragraph ID, not newly numbered paragraphs.
Clients translate them independently, preserving annotation identities and
adjusting annotation offsets relative to each row. Cross-row style/link ranges
are split into distinct annotation IDs pointing to the same original composition
or link; a cross-row formula prevents row classification.

For each structured paragraph, `/fillback` requires `rows[id]` with exactly the
same number of entries, each containing `target_start` / `target_end` offsets into
`translations[id]`. Ranges must be ordered, nonempty and cover all non-whitespace
text. For example, two translated rows can use `[{"target_start": 0,
"target_end": 18}, {"target_start": 19, "target_end": 35}]`. Row boundaries are
explicit; newlines inside an entry do not create additional entries.
Missing, malformed or unknown row ranges return HTTP 400.

Fillback applies annotations inside each row and typesets it in its saved region,
while retaining the parent's ID and draw order. Row glyphs remain contiguous in
the PDF text stream for search/copy. Row metadata survives session recovery;
existing sessions without it retain legacy behavior. Update both Wenyi and the
bridge and extract into fresh state to enable this contract.

## Inline annotation alignment

`/health` advertises `annotation-alignment-v1` and `annotation-best-effort-v1`
in `capabilities`. Clients relying on per-item omission must require the latter.
Each extracted paragraph has an `annotations` list. Entries contain a stable
`id`, `kind` (`formula`, `style` or `link`), `mode: "range"`, and half-open
`source_start` / `source_end` offsets into that paragraph's exact `source`.
Offsets count Unicode code points, not UTF-8 bytes or UTF-16 code units.
`composition_index` identifies the frozen formula or style composition;
`link_id` identifies a record in the paragraph document's `links` list.
Clients must not change these identities or regenerate the referenced IL.
Source offsets are captured before BabelDOC groups styles and formulas;
discontinuous style and link runs have separate annotation entries.

Small corner markers inside prose are removed from translatable `source` and
represented by `mode: "point"` with equal start/end offsets. Their original IL
and any attached `link_ids` remain in the session. `original_source`, when present,
records the original paragraph Unicode for snapshot validation. Standalone markers
retain nonempty source text and range alignment.

Wenyi uses its existing annotation aligner after translating the paragraph.
The optional `/fillback` `annotations` object is keyed by paragraph ID:

```json
{
  "0:3": {
    "target_digest": "SHA-256 hex digest of the exact UTF-8 translation",
    "placements": [
      {
        "id": "formula:1",
        "mode": "range",
        "target_start": 8,
        "target_end": 13,
        "status": "aligned"
      }
    ]
  }
}
```

Fillback keeps the supplied translation and applies each valid annotation
independently, including when another item in the same paragraph fails.
Placements need a matching digest, `status: "aligned"`, valid offsets and mode.
Missing, duplicate, unresolved or invalid items are omitted; unknown item IDs are
ignored. A missing/stale digest invalidates all positions for that paragraph,
not its translated body. Overlapping formulas or incompatible overlapping styles
omit only the conflicting participants. Unchanged source text can use identity
offsets without an alignment request.

Successful placements restore original formula IL in place of its aligned target
span, insert corner-marker IL at aligned points, and reapply style runs. Failed
placements leave the supplied body unchanged, without adding the original object,
style or link at a guessed position. Mathematical content is not regenerated from
translated text. Submitted placements are saved with text in `translations.json`.
Unknown paragraph IDs and missing, unknown or blank translations still return
HTTP 400; these are invalid requests, not annotation alignment failures.

The bridge captures URI and internal page links, including resolved named
destinations, before BabelDOC clears annotations, then rebuilds their clickable
rectangles from the actual typeset glyphs, one rectangle per line. Image-only
links retain their original rectangles. Internal destinations keep their original
page coordinates and are remapped to selected output pages; links to omitted
destination pages are omitted. Other action types are not reconstructed.
Visible-glyph mismatches omit the affected paragraph's text links rather than
attaching them to unrelated text; other paragraphs remain independent.
An item with no rendered glyphs is omitted independently.
Spaces removed at line boundaries do not invalidate the mapping.

Every successful fillback returns a compact JSON summary in the
`X-Wenyi-PDF-Annotation-Stats` response header and writes `annotation_stats.json`
in the session directory. The file includes per-item paragraph/annotation IDs,
kind, validation status and skip reason, without copying paragraph text.
The summary counts `total`, `aligned`, `applied`, `skipped`,
`alignment_pass_rate` and `application_rate`; it also breaks down `by_kind`,
`reasons`, `translated` and `source_identity`. Rates are fractions or `null` for
an empty denominator. `aligned` means that placement validation passed, not that
the model's semantic choice is proven correct; `applied` also excludes conflicts
and link-render failures. Source-identity items are counted separately so they
do not inflate translated-text rates. Statistics describe one request, not a
cumulative counter. Protected vertical paragraphs do not participate in alignment
statistics. Wenyi records the summary in its CLI log.

Update both client and bridge and extract the original PDF again to enable this
for older projects. Existing sessions without annotation metadata retain the
legacy text-only behavior; recovery does not rerun extraction to supplement them.

## Session recovery

After `/extract`, the bridge saves the unmodified BabelDOC IL, corrected input
PDF, MediaBox information, paragraph index, page selection and dependency versions
as a session snapshot. The compressed native graph also preserves shared aliases,
lazy graphics-state history and the parser's original page-object map.
`session.json` is committed last, so only complete snapshots can be restored.

A service restart can lazily restore the original `session_id` without rerunning
layout recognition. Every `/fillback` loads a fresh copy of the frozen IL,
so retries do not reuse objects modified by an earlier fillback or typesetting pass.
Unknown, missing or blank translations are rejected rather than silently skipped.

Recovery requires matching Python/BabelDOC versions, the pinned native engine
revision and valid snapshot file checksums. The 0.7.1 bridge uses a new native
snapshot format: 0.5/0.6 pickle and legacy JSON sessions are rejected, not loaded
or automatically migrated.
Finish old tasks in their original environment, or run `/extract` again from the
original PDF in the new environment.

See [cache and session directories](installation.md#caches-and-sessions) to keep
sessions outside the system temporary directory.

## Cleanup

Call `DELETE /session/{id}` after fillback to release the PDF, IL and other session
files. Before deletion, the bridge releases unreachable native PDF file handles.
If files are still busy, it returns 503 and keeps the loaded session for a retry;
it does not report successful cleanup while files remain.

## Layout diagnostics

Fillback does not draw BabelDOC layout boxes or debug class labels such as
`plain text`, `title` and `figure_caption` by default.
For layout diagnostics, enable debug output before starting the service:

```bash
export WENYI_BABELDOC_DEBUG=1
```
