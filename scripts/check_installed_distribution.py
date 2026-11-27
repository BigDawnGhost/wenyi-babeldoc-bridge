"""Smoke-test an installed bridge distribution using selected checkout tests."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from importlib.machinery import EXTENSION_SUFFIXES
from importlib.metadata import Distribution, distribution
from importlib.util import find_spec
from pathlib import Path

PACKAGE = "wenyi_babeldoc_bridge"
PROJECT = "wenyi-babeldoc-bridge"


def check_package_files(installed: Distribution) -> None:
    files = installed.files
    if not files:
        raise SystemExit("Installed bridge is missing its file manifest")
    leaked = [
        file.as_posix()
        for file in files
        if "tests" in file.parts or file.name.startswith("test_")
    ]
    if leaked:
        raise SystemExit(f"Installed bridge contains test files: {sorted(leaked)}")

    paths = {Path(str(installed.locate_file(file))).resolve() for file in files}
    modules = (
        "",
        "desktop_runtime",
        "native",
        "pipeline",
        "probe_extract",
        "probe_fillback",
        "schema",
        "server",
        "smoke_client",
        "preservation.layout",
        "preservation.geometry",
        "preservation.boxes",
        "preservation.toc",
        "_native",
    )
    for module in modules:
        name = f"{PACKAGE}.{module}" if module else PACKAGE
        spec = find_spec(name)
        origin = spec.origin if spec else None
        if not origin or Path(origin).resolve() not in paths:
            raise SystemExit(f"{name} does not resolve to the installed bridge")
        if module == "_native" and not origin.endswith(tuple(EXTENSION_SUFFIXES)):
            raise SystemExit(f"{name} is not a compiled extension")


def check_service(installed: Distribution) -> None:
    from fastapi.testclient import TestClient

    from wenyi_babeldoc_bridge import server

    entry = next(
        (
            item
            for item in installed.entry_points
            if item.group == "console_scripts" and item.name == PROJECT
        ),
        None,
    )
    if entry is None or not callable(entry.load()):
        raise SystemExit("Bridge console entry point is not callable")
    if server.app.version != installed.version:
        raise SystemExit("Bridge API and installed package versions disagree")
    with TestClient(server.app) as client:
        response = client.get("/health")
        if response.status_code != 200 or response.json()["ok"] is not True:
            raise SystemExit(f"Bridge health check failed: {response.text}")


def run_regressions(tests: Path, modules: list[str]) -> None:
    sys.path.insert(0, str(tests.resolve()))
    suite = unittest.TestSuite()
    for module in modules:
        if not (tests / f"{module}.py").is_file():
            raise SystemExit(f"Missing external unittest module: {module}")
        cases = unittest.defaultTestLoader.loadTestsFromName(module)
        if cases.countTestCases() == 0:
            raise SystemExit(f"No installed bridge regressions found in {module}")
        suite.addTests(cases)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun == len(result.skipped):
        raise SystemExit("Installed bridge regressions failed or all were skipped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version")
    parser.add_argument("tests", type=Path)
    parser.add_argument("modules", nargs="+")
    args = parser.parse_args()

    # -I protects this process; drop PYTHONPATH for regression subprocesses too.
    os.environ.pop("PYTHONPATH", None)
    os.environ["WENYI_BABELDOC_INTEGRATION"] = "0"
    installed = distribution(PROJECT)
    if args.expected_version and installed.version != args.expected_version:
        raise SystemExit(f"Unexpected bridge version: {installed.version}")
    with tempfile.TemporaryDirectory() as state:
        os.environ["WENYI_BABELDOC_STATE_DIR"] = state
        check_package_files(installed)
        check_service(installed)
        run_regressions(args.tests, args.modules)


if __name__ == "__main__":
    main()
