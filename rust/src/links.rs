//! Link geometry in the parser's bottom-up PDF coordinate frame.
//! PyMuPDF still owns PDF actions, page rotation and transformation matrices.

use crate::policy::{Rect, Span, TextIndex, overlaps};
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};

fn contains_center([x, y, x2, y2]: Rect, [left, bottom, right, top]: Rect) -> bool {
    let (x, y) = ((x + x2) / 2., (y + y2) / 2.);
    left <= x && x <= right && bottom <= y && y <= top
}

fn rectangles(glyphs: impl Iterator<Item = Rect>) -> Vec<Rect> {
    let mut lines: Vec<Rect> = Vec::new();
    for rect in glyphs {
        let [x, y, x2, y2] = rect;
        if x >= x2 || y >= y2 {
            continue;
        }
        // Preserve first-match order, not nearest-line or transitive merging.
        let line = lines
            .iter_mut()
            .find(|old| old[3].min(y2) - old[1].max(y) > (old[3] - old[1]).min(y2 - y) * 0.5);
        match line {
            Some(old) => *old = [old[0].min(x), old[1].min(y), old[2].max(x2), old[3].max(y2)],
            None => lines.push(rect),
        }
    }
    lines
}

fn source_ranges(text: &TextIndex, mut spans: Vec<Span>) -> Vec<Span> {
    spans.sort_unstable();
    let mut result: Vec<Span> = Vec::new();
    for (start, end) in spans {
        if let Some(last) = result.last_mut()
            && text.blank(last.1, start)
        {
            last.1 = last.1.max(end);
        } else {
            result.push((start, end));
        }
    }
    result
}

type SourceGlyph = (usize, Span, Option<Rect>);
type SourceRanges = (Vec<Vec<Span>>, Vec<Vec<Span>>);

#[pyfunction]
pub(crate) fn inline_source_ranges(
    py: Python<'_>,
    source: String,
    kinds: Vec<Option<bool>>, // None: ordinary run; false: style; true: formula
    glyphs: Vec<SourceGlyph>,
    links: Vec<Rect>,
) -> SourceRanges {
    py.detach(|| {
        let text = TextIndex::new(&source);
        let mut spans = vec![vec![]; kinds.len()];
        for &(index, span, _) in &glyphs {
            if kinds.get(index).is_some_and(Option::is_some) {
                spans[index].push(span);
            }
        }
        let compositions = kinds
            .into_iter()
            .zip(spans)
            .map(|(kind, spans)| {
                if kind == Some(true) && !spans.is_empty() {
                    vec![(
                        spans.iter().map(|span| span.0).min().unwrap(),
                        spans.iter().map(|span| span.1).max().unwrap(),
                    )]
                } else {
                    source_ranges(&text, spans)
                }
            })
            .collect();
        let links = links
            .into_iter()
            .map(|rect| {
                source_ranges(
                    &text,
                    glyphs
                        .iter()
                        .filter(|glyph| glyph.2.is_some_and(|box_| contains_center(box_, rect)))
                        .map(|glyph| glyph.1)
                        .collect(),
                )
            })
            .collect();
        (compositions, links)
    })
}

#[pyfunction]
pub(crate) fn original_link_boxes(
    py: Python<'_>,
    glyphs: Vec<(Rect, Rect)>,
    links: Vec<Rect>,
) -> Vec<Vec<Rect>> {
    py.detach(|| {
        links
            .into_iter()
            .map(|link| {
                rectangles(
                    glyphs
                        .iter()
                        .filter(|glyph| contains_center(glyph.0, link))
                        .map(|glyph| glyph.1),
                )
            })
            .collect()
    })
}

type PlannedGlyph = (String, usize, usize, Option<String>);
type LinkRange = (Span, Vec<String>);

#[pyfunction]
pub(crate) fn rendered_link_boxes(
    py: Python<'_>,
    visible: Vec<(String, Rect)>,
    plan: Vec<PlannedGlyph>,
    links: Vec<LinkRange>,
) -> Option<Vec<Vec<Rect>>> {
    py.detach(|| {
        if visible.len() != plan.len()
            || visible
                .iter()
                .zip(&plan)
                .any(|(actual, expected)| actual.0 != expected.0)
        {
            return None;
        }
        Some(
            links
                .into_iter()
                .map(|(range, objects)| {
                    let objects: HashSet<_> = objects.into_iter().collect();
                    rectangles(visible.iter().zip(&plan).filter_map(
                        |((_, rect), (_, start, end, object))| {
                            (overlaps((*start, *end), range)
                                || object.as_ref().is_some_and(|id| objects.contains(id)))
                            .then_some(*rect)
                        },
                    ))
                })
                .collect(),
        )
    })
}

type SavedLink = (i64, Option<i64>, bool, Rect, Vec<Rect>);
type OutputLink = (usize, usize, Option<usize>, Vec<Rect>);

#[pyfunction]
pub(crate) fn select_output_links(
    py: Python<'_>,
    pages: Vec<i64>,
    links: Vec<SavedLink>,
) -> Vec<OutputLink> {
    py.detach(|| {
        let pages: HashMap<_, _> = pages.into_iter().enumerate().map(|(i, n)| (n, i)).collect();
        links
            .into_iter()
            .enumerate()
            .filter_map(|(i, (page, target, text_bound, original, mut boxes))| {
                let page = *pages.get(&page)?;
                let target = match target {
                    Some(number) => Some(*pages.get(&number)?),
                    None => None,
                };
                if boxes.is_empty() {
                    if text_bound {
                        return None;
                    }
                    boxes.push(original);
                }
                Some((i, page, target, boxes))
            })
            .collect()
    })
}
