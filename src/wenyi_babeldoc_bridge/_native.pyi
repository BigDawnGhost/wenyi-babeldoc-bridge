"""Python signatures of the bridge-owned PyO3 API in rust/src/lib.rs."""

from collections.abc import Sequence

BABELDOC_VERSION: str
BABELDOC_REVISION: str

_Span = tuple[int, int]
_Rect = tuple[float, float, float, float] | list[float]

def math_attachment_candidates(
    bases: Sequence[tuple[int, int, _Rect, float]],
    marks: Sequence[tuple[int | None, int, _Rect, float, bool]],
) -> list[list[tuple[int, str]]]: ...
def protect_source(
    source: str,
    tokens: Sequence[tuple[_Span, bool, int]],
    seeds: Sequence[_Span],
    atomic: Sequence[_Span],
    glyphs: Sequence[tuple[_Span, _Rect, float, int | None, int | None, bool]],
) -> tuple[str, list[_Span], list[int]]: ...
def exact_link_styles(
    styles: Sequence[tuple[_Span, _Span]], links: Sequence[tuple[_Span, _Span]]
) -> list[bool]: ...
def target_runs(
    len: int,
    formulas: Sequence[tuple[int, _Span]],
    styles: Sequence[tuple[int, _Span, bool]],
) -> list[tuple[bool, int | None, _Span]]: ...
def inline_source_ranges(
    source: str,
    kinds: Sequence[bool | None],
    glyphs: Sequence[tuple[int, _Span, _Rect | None]],
    links: Sequence[_Rect],
) -> tuple[list[list[_Span]], list[list[_Span]]]: ...
def original_link_boxes(
    glyphs: Sequence[tuple[_Rect, _Rect]], links: Sequence[_Rect]
) -> list[list[list[float]]]: ...
def rendered_link_boxes(
    visible: Sequence[tuple[str, _Rect]],
    plan: Sequence[tuple[str, int, int, str | None]],
    links: Sequence[tuple[_Span, Sequence[str]]],
) -> list[list[list[float]]] | None: ...
def select_output_links(
    pages: Sequence[int],
    links: Sequence[tuple[int, int | None, bool, _Rect, Sequence[_Rect]]],
) -> list[tuple[int, int, int | None, list[list[float]]]]: ...
def annotation_conflicts(
    candidates: Sequence[tuple[_Span, tuple[object, bool] | None]],
) -> list[int]: ...
def partition_annotation_spans(
    items: Sequence[_Span], rows: Sequence[_Span]
) -> list[list[tuple[int, int, int]]]: ...
def row_annotation_placements(
    rows: Sequence[tuple[_Span, _Span]],
    items: Sequence[tuple[_Span, _Span | None]],
) -> list[list[tuple[int, _Span | None]]]: ...

class FontAssets:
    def __init__(self, json: str) -> None: ...

class Document:
    @staticmethod
    def parse(path: str, pages: list[int] | None = None) -> Document: ...
    @staticmethod
    def restore(json: str) -> Document: ...
    @staticmethod
    def restore_checkpoint(path: str, sha256: str) -> Document: ...
    def write_checkpoint(self, path: str) -> str: ...
    def snapshot(self) -> str: ...
    def artifact(self) -> str: ...
    def replace_artifact(self, json: str) -> None: ...
    def layout(self, json: str, debug: bool) -> None: ...
    def paragraphs(
        self,
        fonts: FontAssets,
        debug: bool,
        split_short_lines: bool,
        short_line_split_factor: float,
    ) -> None: ...
    def styles(self, fonts: FontAssets) -> None: ...
    def typeset(self, fonts: FontAssets, language: str) -> None: ...
    def write(self, source: str, output: str, fonts: FontAssets) -> None: ...
