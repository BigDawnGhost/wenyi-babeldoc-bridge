# Wenyi BabelDOC Bridge repository guide for coding agents

This guide applies repository-wide. Read the relevant source, tests and README
before editing. More specific `AGENTS.md` files take precedence within their directories.

## Scope and license boundary

`wenyi-babeldoc-bridge` is an independent **AGPL-3.0-only** HTTP service. It extracts
stable PDF paragraphs with BabelDOC, accepts Wenyi's translations, and typesets
them using the same frozen intermediate representation (IL).

- Wenyi is MIT-licensed. Communication must use HTTP/JSON/multipart only.
- Never import this package, BabelDOC or pdf2zh into Wenyi, or copy AGPL code into it.
- Support Python 3.10–3.13, BabelDOC `>=0.5.20,<0.6.0` and PyMuPDF `<1.25.3`.
- Prefer `uv`. Install BabelDOC only in this repository's isolated environment.

## Code map

Paths below are relative to `src/wenyi_babeldoc_bridge/`:

| File | Responsibility |
| --- | --- |
| `server.py` | FastAPI endpoints, uploads, session registry, error mapping and cleanup |
| `pipeline.py` | BabelDOC IL processing, extraction, translation injection and PDF output |
| `schema.py` | Pure exchange models, stable paragraph IDs and validation |
| `desktop_runtime.py` | Authenticated Desktop process, offline assets and parent lifecycle |
| `smoke_client.py` | Real HTTP extract → fillback → delete smoke client |
| `probe_extract.py`, `probe_fillback.py` | Manual BabelDOC probes, not service entry points |
| `test_*.py` | Schema, snapshot, Desktop runtime, packaging and publication tests |

At the repository root, `scripts/` contains Desktop build and release tooling,
`README.md` documents setup and protocols, and `THIRD_PARTY.md` covers bundled materials.

## Architecture and state invariants

- Keep the call path `Wenyi HTTP client → FastAPI server → pipeline → BabelDOC`.
  The schema layer must not depend on the server or pipeline.
- Extraction persists the original IL, corrected PDF, MediaBox data, paragraph
  index, page selection and versions. Commit `session.json` atomically and last;
  only complete snapshots may survive a process restart.
- Recovery must not rerun layout analysis. Before unpickling internal state,
  validate paths, hashes, and Python/BabelDOC versions. Never load uploaded
  pickles or pickles outside the session directory.
- Fillback mutates IL. Load a fresh copy of the frozen snapshot for every request;
  never reuse an injected or typeset object. Retries must remain idempotent.
- Protect `_SESSIONS` with `_LOCK`. Failed extraction and explicit deletion must
  clean only the affected session, never the shared temporary root.
- Reduce upload filenames to their basename. Write runtime data only within the
  session directory; never trust client-supplied absolute paths.
- Paragraph IDs are `"{page}:{index}"`, where `index` is the original paragraph
  position in the page IL. Filtering must not renumber IDs; fillback uses the same positions.
- Reject unknown IDs, missing translations and blank translations. Never silently
  skip translations or inject them into the wrong paragraph.
- Preserve formulas, placeholders, styles, boxes, layout/debug IDs and render order.
  Changes to paragraph splitting or multiline tables of contents need both layout
  and ID-mapping checks.
- BabelDOC's `high_level` and IL classes are unstable APIs. Dependency upgrades
  require extraction, fillback, page-selection and output-PDF validation, not just imports.
- Public schema or HTTP changes must update the README, smoke client, and Wenyi's
  HTTP bridge client and tests together.

## Development and validation

Create an isolated environment:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv -e .
```

Match Wenyi's pre-commit baseline with Ruff 0.12.7. Apply lint fixes before formatting:

```bash
uvx --from ruff==0.12.7 ruff check --fix .
uvx --from ruff==0.12.7 ruff format .
uvx --from ruff==0.12.7 ruff check .
uvx --from ruff==0.12.7 ruff format --check .
```

Run unit tests from the repository root:

```bash
PYTHONPATH=src uv run --no-project --python .venv python -m unittest discover \
  -s src/wenyi_babeldoc_bridge -p 'test_*.py'
git diff --check
```

Real BabelDOC checks require the isolated environment and an explicitly supplied
PDF. Do not read, process or commit private PDFs by default. For IL, layout or
page-selection changes, use public-domain or synthetic samples to verify:

1. `/extract` returns a valid schema and stable paragraph IDs.
2. Complete translations fill back; missing and unknown IDs fail.
3. The monolingual PDF contains the translations with reasonable page count,
   selection and basic layout.
4. `DELETE /session/{session_id}` releases the session and its files.

## Code and delivery

- Keep Python 3.10 compatibility.
- Prefer pure schema validators with fast, deterministic tests independent of BabelDOC.
- Limit broad exception handling to BabelDOC compatibility fallbacks and HTTP error
  boundaries. Preserve clear errors rather than reporting false success.
- Never commit virtual environments, sessions, generated PDFs, real books, caches
  or debug output.
- Preserve unrelated user changes. Stage only task files; do not clean or overwrite
  unrelated data.
- Before committing, run Ruff check, Ruff format check, unit tests and `git diff --check`.
  Commit or push only when explicitly requested, using Conventional Commits.

## Git and releases

- `main` is the default and only long-lived integration branch. Start short-lived
  branches from the latest `origin/main`; PRs target `main` directly.
- Verify remotes before pushing. The publication remote is
  `https://github.com/BigDawnGhost/wenyi-babeldoc-bridge.git`, not Delta's `local`
  backlink. Do not substitute Wenyi's workflow names or checks for this repository's.
- Before merging, require the current PR revision's complete **Desktop plugin**
  workflow to pass: models, four platform runtimes and HTTP smoke tests, and final
  manifest/source assembly. Old or partial results do not count. Use a merge commit;
  never push feature changes directly to `main` or force-push.
- The merged `main` commit must pass its own build before it can be released.
  Manual runs are diagnostic; successful branch builds do not authorize merging
  or publication.
- Publication requires explicit approval. Use the verified `main` build, a draft
  stable version matching `pyproject.toml`, and the complete verified asset set
  before publishing as latest. Builds are read-only and never publish automatically.
  Never overwrite tags or assets. See [README.md](README.md#development-and-releases)
  for the publication workflow and [plugin protocol](README.md#desktop-plugin).
- Keep historical release/publish branches and published tags unless removal is
  explicitly requested. Do not rewrite them or merge their commits wholesale;
  agree on migration scope first.
