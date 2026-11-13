"""Generate the native artifact reader from the pinned upstream IL schema."""

from __future__ import annotations

import argparse
import dataclasses
import runpy
import subprocess
import sys
from pathlib import Path


def generate(source: Path, destination: Path) -> None:
    sys.path.insert(0, str(source / "scripts"))
    from generate_il_rust import rust_type
    from il_rust_m import fields

    schema = runpy.run_path(
        str(source / "babeldoc/format/pdf/document_il/il_version_1.py")
    )
    classes = [
        value
        for value in schema.values()
        if isinstance(value, type) and dataclasses.is_dataclass(value)
    ]
    lines = [
        "// Generated from BabelDOC 0.7.1's field declarations; do not edit by hand.",
        "impl Loader {",
        "fn data(&mut self, kind: &str, value: &Value, path: &str) -> Result<NodeData> {",
        "Ok(match kind {",
    ]
    for cls in classes:
        name = cls.__name__
        if name == "PdfPath":
            lines.append(
                '"PdfPath" => NodeData::PdfPath(DataPdfPath::new('
                'scalar(&value["x"])?, scalar(&value["y"])?, '
                'scalar::<Option<String>>(&value["op"])?.map(PathOp::from), '
                'scalar(&value["has_xy"])?)),'
            )
            continue
        lines.append(f'"{name}" => NodeData::{name}(Data{name} {{')
        for _, field, optional, many, child, scalar_type in fields(cls, rust_type):
            key = f'value["{field}"]'
            location = f'&format!("{{path}}.{field}")'
            if child:
                method = "many" if many else "optional" if optional else "edge"
                expression = f'self.{method}("{child}", &{key}, {location})?'
            elif scalar_type == "Option<Instructions>":
                expression = f"self.instructions(&{key})?"
            else:
                expression = f"scalar::<{scalar_type}>(&{key})?"
                if name == "PdfCurve" and field == "ctm":
                    expression = f"({expression}).into()"
            ident = "r#box" if field == "box" else field
            lines.append(f"{ident}: {expression},")
        lines.append("}),")
    lines.extend(
        [
            '_ => return Err(format!("unknown IL kind: {kind}").into()),',
            "})",
            "}",
            "}",
        ]
    )
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    revision = subprocess.check_output(
        ["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != "d922e2b0c5a353bde8731921eb442c07ae75849d":
        raise SystemExit("Use the unmodified BabelDOC v0.7.1 source checkout")
    generate(args.source, args.output)
