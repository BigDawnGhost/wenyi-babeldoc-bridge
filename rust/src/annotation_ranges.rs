//! Half-open text ranges, with separate rules for point formulas and row edges.
use pyo3::prelude::*;

type Span = (i64, i64);
type ConflictCandidate = (Span, Option<(Py<PyAny>, bool)>);
type RowPart = (usize, i64, i64);
type RowPlacement = (usize, Option<Span>);

// Only visit geometrically overlapping pairs. Points must come before ranges
// with the same start, and must never join the active set themselves.
fn visit_overlaps(
    mut spans: Vec<(usize, Span)>,
    mut visit: impl FnMut(usize, usize) -> PyResult<()>,
) -> PyResult<()> {
    spans.sort_unstable_by_key(|&(_, (start, end))| (start, start != end));
    let mut active: Vec<(usize, i64)> = Vec::new();
    for (index, (start, end)) in spans {
        active.retain(|&(_, right)| start < right);
        for &(peer, _) in &active {
            visit(index.min(peer), index.max(peer))?;
        }
        if start < end {
            active.push((index, end));
        }
    }
    Ok(())
}

#[pyfunction]
fn annotation_conflicts(
    py: Python<'_>,
    candidates: Vec<ConflictCandidate>,
) -> PyResult<Vec<usize>> {
    let mut styles = Vec::new();
    let mut formulas = Vec::new();
    for (index, &((start, end), ref style)) in candidates.iter().enumerate() {
        match style {
            Some(_) if start < end => styles.push((index, (start, end))),
            None if start <= end => formulas.push((index, (start, end))),
            _ => (),
        }
    }
    // Record each participant's first pair in the original traversal order,
    // without buffering every pair for densely overlapping annotations.
    let mut first = vec![None; candidates.len()];
    let mut mark = |i, j| {
        let pair = (i, j);
        for index in [i, j] {
            let entry: &mut Option<(usize, usize)> = &mut first[index];
            if entry.is_none_or(|previous| pair < previous) {
                *entry = Some(pair);
            }
        }
        Ok(())
    };
    if formulas.len() > 1 {
        py.detach(|| visit_overlaps(formulas, &mut mark))?;
    }
    if styles.len() > 1 {
        visit_overlaps(styles, |i, j| {
            let (a, a_style) = &candidates[i];
            let (b, b_style) = &candidates[j];
            let (a_style, a_linked) = a_style.as_ref().unwrap();
            let (b_style, b_linked) = b_style.as_ref().unwrap();
            // Keep Python's value comparison, including unhashable styles.
            if a_style.bind(py).ne(b_style.bind(py))? {
                // An exact link-backed style can carve a hole in a containing
                // prose style, even when the target spans have equal bounds.
                let allowed = match (a_linked, b_linked) {
                    (true, false) => b.0 <= a.0 && a.1 <= b.1,
                    (false, true) => a.0 <= b.0 && b.1 <= a.1,
                    _ => false,
                };
                if !allowed {
                    mark(i, j)?;
                }
            }
            Ok(())
        })?;
    }
    let mut conflicts: Vec<_> = first
        .into_iter()
        .enumerate()
        .filter_map(|(index, pair)| Some((pair?, index)))
        .collect();
    conflicts.sort_unstable();
    Ok(conflicts.into_iter().map(|(_, index)| index).collect())
}

fn ordered(rows: &[Span]) -> bool {
    rows.windows(2)
        .all(|w| w[0].0 <= w[1].0 && w[0].1 <= w[1].1)
}

// Rows are validated in source order. Binary-search the two limits, retaining
// the caller's row order even for unvalidated input via the linear fallback.
fn matching_rows(
    rows: &[Span],
    ordered: bool,
    (min_end, max_start): Span,
    inclusive: bool,
) -> impl Iterator<Item = (usize, Span)> + '_ {
    let ends_before = move |end| end < min_end || (!inclusive && end == min_end);
    let starts_after = move |start| start > max_start || (!inclusive && start == max_start);
    let (lo, hi) = if ordered {
        let lo = rows.partition_point(|&(_, end)| ends_before(end));
        let hi = rows.partition_point(|&(start, _)| !starts_after(start));
        (lo.min(hi), hi)
    } else {
        (0, rows.len())
    };
    rows[lo..hi]
        .iter()
        .copied()
        .enumerate()
        .filter_map(move |(index, (start, end))| {
            (!ends_before(end) && !starts_after(start)).then_some((lo + index, (start, end)))
        })
}

#[pyfunction]
fn partition_annotation_spans(
    py: Python<'_>,
    items: Vec<Span>,
    rows: Vec<Span>,
) -> Vec<Vec<RowPart>> {
    py.detach(|| {
        let ordered = ordered(&rows);
        items
            .into_iter()
            .map(|(start, end)| {
                matching_rows(&rows, ordered, (start, end), start == end)
                    .map(|(index, (left, right))| (index, start.max(left), end.min(right)))
                    .collect()
            })
            .collect()
    })
}

#[pyfunction]
fn row_annotation_placements(
    py: Python<'_>,
    rows: Vec<(Span, Span)>,
    items: Vec<(Span, Option<Span>)>,
) -> Vec<Vec<RowPlacement>> {
    py.detach(|| {
        let sources: Vec<_> = rows.iter().map(|&(span, _)| span).collect();
        let ordered = ordered(&sources);
        let mut result = vec![Vec::new(); rows.len()];
        // Append in annotation order, including points in both rows that share
        // their edge. A missing/out-of-row target does not affect membership.
        for (index, ((start, end), placement)) in items.into_iter().enumerate() {
            for (row, _) in matching_rows(&sources, ordered, (end, start), true) {
                let (left, right) = rows[row].1;
                let local = placement
                    .filter(|&(a, b)| left <= a && a <= b && b <= right)
                    .map(|(a, b)| (a - left, b - left));
                result[row].push((index, local));
            }
        }
        result
    })
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(annotation_conflicts, module)?)?;
    module.add_function(wrap_pyfunction!(partition_annotation_spans, module)?)?;
    module.add_function(wrap_pyfunction!(row_annotation_placements, module)?)?;
    Ok(())
}
