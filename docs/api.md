# HTTP API and sessions

[简体中文](zh/api.md) · [Overview](../README.md) · [Installation](installation.md)

## Endpoints

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/extract` | Multipart PDF in `file`, optional `pages`; returns `session_id` and `paragraphs` |
| POST | `/fillback` | JSON `{session_id, translations: {id: text}}`; returns a monolingual PDF |
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
`table` or `title`. Only debug overlays identified by IL `debug_info` are excluded;
there is no length- or text-content-based filter.

After updating and restarting a bridge that previously filtered such text,
extract affected PDFs again. Existing sessions are not migrated or supplemented
automatically.

## Session recovery

After `/extract`, the bridge saves the unmodified BabelDOC IL, corrected input
PDF, MediaBox information, paragraph index, page selection and dependency versions
as a session snapshot. `session.json` is committed last, so only complete snapshots
can be restored.

A service restart can lazily restore the original `session_id` without rerunning
layout recognition. Every `/fillback` loads a fresh copy of the frozen IL,
so retries do not reuse objects modified by an earlier fillback or typesetting pass.
Unknown, missing or blank translations are rejected rather than silently skipped.

Recovery requires the same Python and BabelDOC versions and valid snapshot file
checksums. BabelDOC 0.5 snapshots are not automatically migrated to the native 0.6
parser, and version checks are not bypassed to load their pickle files.
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
