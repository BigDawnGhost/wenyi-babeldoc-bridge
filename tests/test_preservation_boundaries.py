"""Source-tree contracts for the pre-paragraph preservation stage."""

import ast
import unittest
from importlib.util import resolve_name
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
BRIDGE = SRC / "wenyi_babeldoc_bridge"
PRESERVATION = BRIDGE / "preservation"


def imported_names(path: Path) -> set[str]:
    """Include local and function-scoped imports without executing the module."""
    package = ".".join(path.parent.relative_to(SRC).parts)
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_name("." * node.level + (node.module or ""), package)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def children(names: set[str], package: str) -> set[str]:
    prefix = f"{package}."
    return {
        name[len(prefix) :].split(".")[0] for name in names if name.startswith(prefix)
    }


class PreservationBoundaries(unittest.TestCase):
    def test_tests_and_development_scripts_are_not_runtime_dependencies(self):
        self.assertTrue((BRIDGE / "__init__.py").is_file())
        self.assertEqual(sorted(BRIDGE.rglob("test_*.py")), [])
        for path in BRIDGE.rglob("*.py"):
            roots = {name.split(".")[0] for name in imported_names(path)}
            self.assertTrue(roots.isdisjoint({"tests", "scripts"}), path)

    def test_native_adapter_uses_the_single_pre_paragraph_entry(self):
        rules = children(
            imported_names(BRIDGE / "native.py"), f"{BRIDGE.name}.preservation"
        )
        self.assertEqual(rules, {"layout"})

    def test_pre_paragraph_rules_do_not_import_their_callers_or_each_other(self):
        self.assertTrue((PRESERVATION / "layout.py").is_file())
        for path in PRESERVATION.rglob("*.py"):
            names = imported_names(path)
            upstream = children(names, BRIDGE.name) & {
                "native",
                "pipeline",
                "server",
                "rows",
                "lists",
                "protected_objects",
            }
            self.assertFalse(upstream, (path.name, upstream))
            if path.stem in {"boxes", "toc", "geometry"}:
                siblings = children(names, f"{BRIDGE.name}.preservation")
                self.assertTrue(siblings <= {"geometry"}, (path.name, siblings))
