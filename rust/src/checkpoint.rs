//! Stream the existing gzip/JSON checkpoint format without a Python JSON buffer.

use std::{
    fmt::Write as _,
    fs::File,
    io::{self, BufReader, BufWriter, Read, Seek, Write},
    path::Path,
};

use flate2::{Compression, GzBuilder, bufread::MultiGzDecoder};
use serde::{Serialize, de::DeserializeOwned};
use sha2::{Digest, Sha256};

use crate::Result;

struct HashWriter<W>(W, Sha256);

impl<W: Write> Write for HashWriter<W> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let written = self.0.write(bytes)?;
        self.1.update(&bytes[..written]);
        Ok(written)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.0.flush()
    }
}

fn hex(hash: Sha256) -> String {
    let mut text = String::with_capacity(64);
    for byte in hash.finalize() {
        write!(text, "{byte:02x}").expect("writing to a String is infallible");
    }
    text
}

pub(super) fn write(path: &Path, snapshot: &impl Serialize) -> Result<String> {
    let output = HashWriter(BufWriter::new(File::create(path)?), Sha256::new());
    let mut gzip = GzBuilder::new()
        .mtime(0)
        .write(output, Compression::default());
    // Buffer the JSON side of the stream as well, so small serde writes do not
    // each call into the compressor.
    {
        let mut json = BufWriter::with_capacity(64 * 1024, &mut gzip);
        serde_json::to_writer(&mut json, snapshot)?;
        json.flush()?;
    }
    let HashWriter(mut file, hash) = gzip.finish()?;
    file.flush()?;
    Ok(hex(hash))
}

pub(super) fn read<T: DeserializeOwned>(path: &Path, expected: &str) -> Result<T> {
    let mut file = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buffer = vec![0; 256 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
    }
    if hex(hash) != expected {
        return Err("session IL snapshot checksum mismatch".into());
    }
    // Check the compressed file before parsing, using the same open file handle.
    file.rewind()?;
    let gzip = MultiGzDecoder::new(BufReader::new(file));
    Ok(serde_json::from_reader(BufReader::with_capacity(
        64 * 1024,
        gzip,
    ))?)
}
