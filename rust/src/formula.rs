//! Geometry and source-interval kernels for the bridge's formula policy.
use crate::policy::{Rect, Span, TextIndex, overlaps};
use pyo3::{exceptions::PyValueError, prelude::*};
use std::collections::HashMap;

type Base = (usize, usize, Rect, f64); // paragraph, drawing context, logical box, size
type Mark = (Option<usize>, usize, Rect, f64, bool); // same, plus accent vs. script

fn attachment_slot(mark: &Mark, base: &Base) -> Option<&'static str> {
    let (_, _, [x, y, x2, _], small, accent) = *mark;
    let (_, _, [bx, by, bx2, _], size) = *base;
    if size <= 0. || small <= 0. {
        return None;
    }
    let dy = (y - by) / size;
    let ratio = small / size;
    if accent {
        let overlap = x2.min(bx2) - x.max(bx);
        let width = (x2 - x).min(bx2 - bx);
        return (width > 0.
            && overlap >= width * 0.6
            && ((x + x2 - bx - bx2) / 2.).abs() <= size * 0.25
            && (0.12..=0.8).contains(&dy)
            && (0.5..=1.2).contains(&ratio))
        .then_some("accent");
    }
    if !(0.45..=0.8).contains(&ratio) {
        return None;
    }
    let upper = if (0.15..=0.85).contains(&dy) {
        true
    } else if (-0.5..=-0.1).contains(&dy) {
        false
    } else {
        return None;
    };
    let gap = (-0.15 * size)..=(0.25 * size);
    if gap.contains(&(x - bx2)) {
        Some(if upper { "right-upper" } else { "right-lower" })
    } else if gap.contains(&(bx - x2)) {
        Some(if upper { "left-upper" } else { "left-lower" })
    } else {
        None
    }
}

#[derive(Default)]
struct BaseIndex {
    by_x: Vec<usize>,
    max_size: f64,
    max_width: f64,
}

#[pyfunction]
pub(crate) fn math_attachment_candidates(
    py: Python<'_>,
    bases: Vec<Base>,
    marks: Vec<Mark>,
) -> Vec<Vec<(usize, &'static str)>> {
    py.detach(|| {
        let mut contexts: HashMap<_, BaseIndex> = HashMap::new();
        for (i, &(_, context, box_, size)) in bases.iter().enumerate() {
            let group = contexts.entry(context).or_default();
            group.by_x.push(i);
            group.max_size = group.max_size.max(size);
            group.max_width = group.max_width.max((box_[2] - box_[0]).abs());
        }
        for group in contexts.values_mut() {
            group
                .by_x
                .sort_unstable_by(|&a, &b| bases[a].2[0].total_cmp(&bases[b].2[0]));
        }
        marks
            .iter()
            .map(|mark| {
                let Some(group) = contexts.get(&mark.1) else {
                    return vec![];
                };
                let [x, _, x2, _] = mark.2;
                // A conservative window includes both side gaps and overlapping accents.
                // The exact tests below are still the authority at threshold boundaries.
                let margin = group.max_size + group.max_width;
                let left = group
                    .by_x
                    .partition_point(|&i| bases[i].2[0] < x.min(x2) - margin);
                let right = group
                    .by_x
                    .partition_point(|&i| bases[i].2[0] <= x.max(x2) + margin);
                let mut candidates: Vec<_> = group.by_x[left..right]
                    .iter()
                    .filter_map(|&i| {
                        let base = &bases[i];
                        if mark.0.is_some_and(|owner| owner != base.0) {
                            return None;
                        }
                        attachment_slot(mark, base).map(|slot| (i, slot))
                    })
                    .collect();
                // Preserve source/composition order for any ties in Python's evidence rules.
                candidates.sort_unstable_by_key(|row| row.0);
                candidates
            })
            .collect()
    })
}

fn align_regions(regions: Vec<Span>, mut spans: Vec<Span>) -> Result<Vec<Span>, &'static str> {
    spans.sort_unstable();
    spans.dedup();
    let max_ends: Vec<_> = spans
        .iter()
        .scan(0, |max, &(_, end)| {
            *max = end.max(*max);
            Some(*max)
        })
        .collect();
    let mut aligned = Vec::with_capacity(regions.len());
    for (left, right) in regions {
        let hits = |left, right| {
            // The first prefix that extends past left can precede the first actual
            // hit when spans nest. Filter the resulting window using exact overlap.
            let start = max_ends.partition_point(|&end| end <= left);
            let end = spans.partition_point(|&(start, _)| start < right);
            spans[start.min(end)..end]
                .iter()
                .copied()
                .filter(move |&span| overlaps(span, (left, right)))
        };
        let mut matches = hits(left, right);
        let Some((a, b)) = matches.next() else {
            return Err("Mathematical region has no original source glyphs");
        };
        let (left, right) = matches.fold((left.min(a), right.max(b)), |(left, right), (a, b)| {
            (left.min(a), right.max(b))
        });
        if hits(left, right).any(|(a, b)| a < left || right < b) {
            return Err("Mathematical region has ambiguous overlapping glyph spans");
        }
        aligned.push((left, right));
    }
    aligned.sort_unstable();
    let mut merged: Vec<Span> = Vec::new();
    for (left, right) in aligned {
        if let Some(last) = merged.last_mut()
            && left < last.1
        {
            last.1 = last.1.max(right);
        } else {
            merged.push((left, right));
        }
    }
    Ok(merged)
}

type Token = (Span, bool, i8); // can extend a seed, opens (1) or closes (-1) a bracket
type MathGlyph = (Span, Rect, f64, Option<i64>, Option<usize>, bool); // context, native formula, fixed

fn connected(a: &MathGlyph, b: &MathGlyph) -> bool {
    if a.4.is_some() && a.4 == b.4 {
        return true;
    }
    if a.5 || b.5 || a.3 != b.3 {
        return false;
    }
    let [ax, ay, ax2, _] = a.1;
    let [bx, by, bx2, _] = b.1;
    let size = a.2.max(b.2);
    (ax - bx2).max(bx - ax2).max(0.) <= size * 0.65 && (ay - by).abs() <= size * 0.8
}

#[pyfunction]
pub(crate) fn protect_source(
    py: Python<'_>,
    source: String,
    tokens: Vec<Token>,
    mut seeds: Vec<Span>,
    mut atomic: Vec<Span>,
    glyphs: Vec<MathGlyph>,
) -> PyResult<(String, Vec<Span>, Vec<usize>)> {
    py.detach(|| {
        let text = TextIndex::new(&source);
        if tokens
            .iter()
            .any(|&((start, end), _, _)| start >= end || end > text.len())
            || tokens.windows(2).any(|pair| pair[0].0.1 > pair[1].0.0)
        {
            return Err("Invalid mathematical token offsets");
        }
        let mut token_glyphs = vec![vec![]; tokens.len()];
        for glyph in &glyphs {
            let start = tokens.partition_point(|token| token.0.1 <= glyph.0.0);
            for (i, _) in tokens
                .iter()
                .enumerate()
                .skip(start)
                .take_while(|(_, t)| t.0.0 < glyph.0.1)
            {
                token_glyphs[i].push(glyph);
            }
        }

        seeds.sort_unstable();
        atomic.sort_unstable();
        let (mut seed, mut seed_end) = (0, 0);
        let mut selected = Vec::with_capacity(tokens.len());
        for &((start, end), _, _) in &tokens {
            while seed < seeds.len() && seeds[seed].0 < end {
                seed_end = seed_end.max(seeds[seed].1);
                seed += 1;
            }
            selected.push(start < seed_end);
        }
        let seeded = selected.clone();

        let (mut atom, mut atom_end) = (0, 0);
        let edges: Vec<_> = tokens
            .windows(2)
            .enumerate()
            .map(|(i, pair)| {
                while atom < atomic.len() && atomic[atom].0 <= pair[0].0.0 {
                    atom_end = atom_end.max(atomic[atom].1);
                    atom += 1;
                }
                atom_end >= pair[1].0.1
                    || token_glyphs[i]
                        .iter()
                        .any(|a| token_glyphs[i + 1].iter().any(|b| connected(a, b)))
            })
            .collect();
        // Reachability on adjacent tokens: only the destination must be mathematical.
        for (i, &edge) in edges.iter().enumerate() {
            selected[i + 1] |= selected[i] && edge && tokens[i + 1].1;
        }
        for (i, &edge) in edges.iter().enumerate().rev() {
            selected[i] |= selected[i + 1] && edge && tokens[i].1;
        }

        // An unseeded opener has to close within the selected run. The old
        // matching rule counts depth without distinguishing bracket types.
        let mut opens = Vec::new();
        for (i, &(_, _, bracket)) in tokens.iter().enumerate() {
            if !selected[i] {
                for open in opens.drain(..) {
                    selected[open] &= seeded[open];
                }
            } else if bracket == 1 {
                opens.push(i);
            } else if bracket == -1 {
                opens.pop();
            }
        }
        for open in opens {
            selected[open] &= seeded[open];
        }

        let mut regions: Vec<Span> = Vec::new();
        for (i, (&(span, _, _), chosen)) in tokens.iter().zip(selected).enumerate() {
            if !chosen {
                continue;
            }
            if let Some(last) = regions.last_mut()
                && text.blank(last.1, span.0)
                && edges[i - 1]
            {
                last.1 = span.1;
            } else {
                regions.push(span);
            }
        }
        let regions = align_regions(regions, glyphs.into_iter().map(|glyph| glyph.0).collect())?;
        if regions.last().is_some_and(|region| region.1 > text.len()) {
            return Err("Mathematical region extends beyond paragraph source");
        }
        let mut cleaned = String::new();
        let (mut cursor, mut retained) = (0, 0);
        let mut boundaries = Vec::with_capacity(text.len() + 1);
        for &(start, end) in &regions {
            cleaned.push_str(text.slice(&source, cursor, start));
            // Emit one entry for each source position before the removed span,
            // then collapse the positions inside the object to its insertion point.
            let kept = start - cursor;
            boundaries.extend(retained..retained + kept);
            retained += kept;
            boundaries.extend(std::iter::repeat_n(retained, end - start));
            cursor = end;
        }
        cleaned.push_str(text.slice(&source, cursor, text.len()));
        boundaries.extend(retained..=retained + (text.len() - cursor));
        Ok((cleaned, regions, boundaries))
    })
    .map_err(PyValueError::new_err)
}

#[cfg(test)]
mod tests {
    use super::align_regions;

    #[test]
    fn use_whole_glyph_spans_without_accepting_ambiguous_overlap() {
        assert_eq!(
            align_regions(vec![(1, 2), (3, 4)], vec![(1, 4)]),
            Ok(vec![(1, 4)])
        );
        assert_eq!(
            align_regions(vec![(2, 3)], vec![(1, 4), (2, 3)]),
            Ok(vec![(1, 4)])
        );
        assert_eq!(
            align_regions(vec![(1, 2)], vec![(1, 3), (2, 4)]),
            Err("Mathematical region has ambiguous overlapping glyph spans")
        );
        assert_eq!(
            align_regions(vec![(1, 2)], vec![]),
            Err("Mathematical region has no original source glyphs")
        );
    }
}
