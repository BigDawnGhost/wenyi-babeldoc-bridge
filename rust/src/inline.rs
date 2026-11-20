//! Schedule accepted fillback placements without owning IL styles or objects.
use crate::policy::Span;
use pyo3::prelude::*;
use std::{
    cmp::Reverse,
    collections::{BTreeMap, BinaryHeap, HashSet},
};

type AlignedRange = (Span, Span); // exact source and target ranges

#[pyfunction]
pub(crate) fn exact_link_styles(
    py: Python<'_>,
    styles: Vec<AlignedRange>,
    links: Vec<AlignedRange>,
) -> Vec<bool> {
    py.detach(|| {
        let links: HashSet<_> = links.into_iter().collect();
        styles.iter().map(|range| links.contains(range)).collect()
    })
}

type Style = (usize, Span, bool); // item index, target span, link evidence
type TargetRun = (bool, Option<usize>, Span); // formula?, item (or base style), target span

#[pyfunction]
pub(crate) fn target_runs(
    py: Python<'_>,
    len: usize,
    formulas: Vec<(usize, Span)>,
    styles: Vec<Style>,
) -> Vec<TargetRun> {
    py.detach(|| {
        let mut boundaries = vec![0, len];
        let mut by_start: BTreeMap<usize, Vec<(usize, usize)>> = BTreeMap::new();
        for (item, (start, end)) in formulas {
            boundaries.extend([start, end]);
            // The caller orders coincident objects (including legacy target orders).
            by_start.entry(start).or_default().push((item, end));
        }
        let mut events: Vec<_> = styles
            .into_iter()
            .enumerate()
            .map(|(order, (item, (start, end), linked))| {
                boundaries.extend([start, end]);
                (start, (linked, Reverse(order), end, item))
            })
            .collect();
        events.sort_unstable_by_key(|event| event.0);
        let mut events = events.into_iter().peekable();
        let mut active = BinaryHeap::new();
        boundaries.sort_unstable();
        boundaries.dedup();
        let mut runs: Vec<TargetRun> = Vec::new();
        let mut covered = 0;
        for (i, &start) in boundaries.iter().enumerate() {
            if start < covered {
                continue;
            }
            if let Some(objects) = by_start.remove(&start) {
                for (item, end) in objects {
                    runs.push((true, Some(item), (start, end)));
                    covered = end;
                }
                if covered > start {
                    continue;
                }
            }
            let Some(&end) = boundaries.get(i + 1) else {
                break;
            };
            while events.peek().is_some_and(|event| event.0 <= start) {
                active.push(events.next().unwrap().1);
            }
            while active.peek().is_some_and(|entry| entry.2 <= start) {
                active.pop();
            }
            runs.push((false, active.peek().map(|entry| entry.3), (start, end)));
        }
        runs
    })
}
