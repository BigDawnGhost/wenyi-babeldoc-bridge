"""Exercise a frozen plugin over real HTTP using an explicitly synthetic PDF."""

from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import stat
import subprocess
import tempfile
import threading
import zipfile
from collections.abc import Iterable
from pathlib import Path

import httpx
import pymupdf


def verify_fillback_text(text: str, targets: Iterable[str]) -> None:
    normalized = " ".join(text.split())
    assert "Synthetic translated paragraph." in normalized, repr(text)
    for target in targets:
        assert target in normalized, (target, text)


def smoke(executable: Path, models: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="babeldoc-smoke-") as temporary:
        root = Path(temporary)
        if executable.suffix == ".zip":
            runtime = root / "runtime"
            with zipfile.ZipFile(executable) as bundle:
                bundle.extractall(runtime)
                for entry in bundle.infolist():
                    if not entry.is_dir():
                        mode = entry.external_attr >> 16
                        (runtime / entry.filename).chmod(
                            0o755 if mode & stat.S_IXUSR else 0o644
                        )
            executable = runtime / (
                "wenyi-babeldoc-plugin.exe"
                if os.name == "nt"
                else "wenyi-babeldoc-plugin"
            )
        cache = root / "cache"
        with zipfile.ZipFile(models) as bundle:
            bundle.extractall(cache)
        pdf = root / "synthetic.pdf"
        short_translations = {
            "Cis man": "Cis male",
            "Gender": "Sex",
            "Percent": "Ratio",
            "N": "N",
            "15": "15",
            "22.0": "22.0",
            "table": "Table",
            "title": "Title",
            # Equal-length text exercises CMaps/fonts without testing box overflow.
            "中文标签": "中文译文",
        }
        with pymupdf.open() as document:
            for text in (
                "This synthetic first page tests the independent desktop plugin.",
                "A second synthetic page checks selected page identity.",
            ):
                page = document.new_page()
                page.insert_textbox(pymupdf.Rect(72, 72, 500, 300), text, fontsize=14)
            for index, label in enumerate(short_translations):
                page.insert_text(
                    (72 + 278 * (index % 2), 160 + 80 * (index // 2)),
                    label,
                    fontname="helv" if label.isascii() else "china-s",
                    fontsize=14,
                )
            document.save(pdf)
        token = secrets.token_hex(32)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("PYTHON", "WENYI_", "_PYI"))
        }
        env["WENYI_BABELDOC_TOKEN"] = token
        env["WENYI_BABELDOC_DIAGNOSTICS_DIR"] = str(root / "diagnostics")
        # A fully prepared plugin must not need the network while processing PDFs.
        env.update(
            HTTP_PROXY="http://127.0.0.1:1",
            HTTPS_PROXY="http://127.0.0.1:1",
            ALL_PROXY="http://127.0.0.1:1",
            NO_PROXY="127.0.0.1,localhost",
        )
        child = subprocess.Popen(
            [
                str(executable.resolve()),
                "--data-dir",
                str(root / "sessions"),
                "--cache-dir",
                str(cache),
            ],
            cwd=root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ready = queue.Queue()
        errors = []
        threading.Thread(
            target=lambda: ready.put(child.stdout.readline()), daemon=True
        ).start()

        def read_errors():
            for line in child.stderr:
                errors.append(line)

        threading.Thread(target=read_errors, daemon=True).start()
        try:
            print("Waiting for frozen runtime readiness…", flush=True)
            info = json.loads(ready.get(timeout=180))
            assert info["protocol"] == 1 and info["pid"] == child.pid
            assert token not in json.dumps(info)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{info['port']}",
                trust_env=False,
                timeout=180,
            ) as http:
                assert http.get("/health").status_code == 403
                http.headers["Authorization"] = f"Bearer {token}"
                assert http.get("/health").json()["ok"]
                assert (
                    http.get(
                        "/health", headers={"Origin": "https://evil.test"}
                    ).status_code
                    == 403
                )
                print("Authenticated; extracting synthetic page 2…", flush=True)
                with pdf.open("rb") as stream:
                    response = http.post(
                        "/extract",
                        files={"file": ("synthetic.pdf", stream, "application/pdf")},
                        data={"pages": "2"},
                    )
                response.raise_for_status()
                data = response.json()
                rows = data["paragraphs"]["paragraphs"]
                assert rows and all(
                    row["id"] == f"{row['page']}:{row['index']}" for row in rows
                )
                assert all(row["page"] == 1 for row in rows)
                sources = {row["source"].strip() for row in rows}
                short_cells = set(short_translations) - {"table", "title"}
                assert short_cells <= sources, short_cells - sources
                # Layout analysis can merge the last row into "table title".
                # Both real words must survive, regardless of paragraph grouping.
                assert {"table", "title"} <= set(" ".join(sources).split()), sources

                def translate(source):
                    if source in short_translations:
                        return short_translations[source]
                    words = source.split()
                    if words and all(word in short_translations for word in words):
                        return " ".join(short_translations[word] for word in words)
                    return "Synthetic translated paragraph."

                translations = {
                    row["id"]: translate(row["source"].strip()) for row in rows
                }
                print("Extracted stable IDs; checking fillback…", flush=True)
                body = {"session_id": data["session_id"], "translations": translations}
                assert (
                    http.post(
                        "/fillback", json={**body, "translations": {"unknown": "No"}}
                    ).status_code
                    == 400
                )
                assert (
                    http.post(
                        "/fillback", json={**body, "translations": {}}
                    ).status_code
                    == 400
                )
                assert (
                    http.post(
                        "/fillback",
                        json={
                            **body,
                            "translations": {**translations, rows[0]["id"]: ""},
                        },
                    ).status_code
                    == 400
                )
                response = http.post("/fillback", json=body)
                response.raise_for_status()
                with pymupdf.open(stream=response.content, filetype="pdf") as output:
                    assert len(output) == 1
                    text = "".join(page.get_text() for page in output)
                    verify_fillback_text(text, short_translations.values())
                print("Restarting to verify frozen session recovery…", flush=True)
                child.stdin.close()
                child.wait(timeout=15)
                assert child.returncode == 0
                child = subprocess.Popen(
                    child.args,
                    cwd=root,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                threading.Thread(
                    target=lambda: ready.put(child.stdout.readline()), daemon=True
                ).start()
                threading.Thread(target=read_errors, daemon=True).start()
                info = json.loads(ready.get(timeout=180))
                assert info["pid"] == child.pid and info["protocol"] == 1
                http.base_url = f"http://127.0.0.1:{info['port']}"
                assert http.get("/health").json()["loaded_sessions"] == 0
                response = http.post("/fillback", json=body)
                response.raise_for_status()
                with pymupdf.open(stream=response.content, filetype="pdf") as output:
                    text = "".join(page.get_text() for page in output)
                    verify_fillback_text(text, short_translations.values())
                assert http.delete(f"/session/{data['session_id']}").status_code == 200
                assert not (root / "sessions" / data["session_id"]).exists()
            child.stdin.close()
            child.wait(timeout=15)
            assert child.returncode == 0
            diagnostics = "\n".join(errors) + "\n".join(
                log.read_text(encoding="utf-8")
                for log in (root / "diagnostics").glob("*.log")
            )
            assert not any(
                failure in diagnostics
                for failure in (
                    "Traceback (most recent call last)",
                    "Font subsetting timeout",
                    "failed with exit code",
                    "Falling back to save",
                )
            ), "A frozen worker failed even though the PDF fallback succeeded"
        except BaseException:
            # Give the owner watchdog a chance to reap its PDF worker children.
            if not child.stdin.closed:
                child.stdin.close()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            # Synthetic test output only. Never print the token or inherited environment.
            for error in errors:
                print(error.replace(token, "[redacted]"))
            for log in sorted((root / "diagnostics").glob("*.log")):
                print(f"Frozen process log: {log.name}", flush=True)
                print(log.read_text(encoding="utf-8").replace(token, "[redacted]"))
            raise
        print(
            "Frozen plugin: authentication, selected-page short-cell/CJK extract, "
            "fillback, delete and EOF shutdown passed."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("models", type=Path)
    args = parser.parse_args()
    smoke(args.executable, args.models)
