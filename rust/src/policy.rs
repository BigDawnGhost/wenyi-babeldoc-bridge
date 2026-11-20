//! Transient indexes for policy over Python's IL projection. Offsets count
//! Unicode code points (the HTTP contract), never UTF-8 bytes.

pub(crate) type Span = (usize, usize);
pub(crate) type Rect = [f64; 4];

pub(crate) fn overlaps((a, b): Span, (c, d): Span) -> bool {
    a < d && c < b
}

pub(crate) struct TextIndex {
    bytes: Vec<usize>,
    visible: Vec<usize>,
}

impl TextIndex {
    pub(crate) fn new(text: &str) -> Self {
        let mut bytes = Vec::new();
        let mut visible = vec![0];
        for (byte, char) in text.char_indices() {
            bytes.push(byte);
            // Python str.isspace also counts these four control characters.
            let space = char.is_whitespace() || ('\x1c'..='\x1f').contains(&char);
            visible.push(visible.last().unwrap() + usize::from(!space));
        }
        bytes.push(text.len());
        Self { bytes, visible }
    }

    pub(crate) fn len(&self) -> usize {
        self.bytes.len() - 1
    }

    pub(crate) fn blank(&self, start: usize, end: usize) -> bool {
        // Python slicing clamps endpoints and returns empty on a reversed span.
        start >= end || self.visible[start.min(self.len())] == self.visible[end.min(self.len())]
    }

    pub(crate) fn slice<'a>(&self, source: &'a str, start: usize, end: usize) -> &'a str {
        &source[self.bytes[start]..self.bytes[end]]
    }
}
