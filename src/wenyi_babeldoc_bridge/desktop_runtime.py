"""Private, authenticated Desktop entry point for the independent AGPL runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import secrets
import socket
import sys
import threading
from pathlib import Path


class PrivateBoundary:
    """No browser access, DNS rebinding, or unauthenticated loopback requests."""

    def __init__(self, app, port: int, token: str):
        self.app = app
        self.host = f"127.0.0.1:{port}".encode()
        self.authorization = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = scope.get("headers", [])
            hosts = [v for k, v in headers if k.lower() == b"host"]
            tokens = [v for k, v in headers if k.lower() == b"authorization"]
            origins = [v for k, v in headers if k.lower() == b"origin"]
            if (
                hosts != [self.host]
                or origins
                or len(tokens) != 1
                or not secrets.compare_digest(tokens[0], self.authorization)
            ):
                await send(
                    {"type": "http.response.start", "status": 403, "headers": []}
                )
                await send({"type": "http.response.body", "body": b"Forbidden"})
                return
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


def configure_assets(cache: Path) -> None:
    """Point BabelDOC at the separately downloaded, verified offline asset pack."""
    import babeldoc.const as const

    const.CACHE_FOLDER = cache
    const.TIKTOKEN_CACHE_FOLDER = cache / "tiktoken"
    os.environ["TIKTOKEN_CACHE_DIR"] = str(const.TIKTOKEN_CACHE_FOLDER)
    from babeldoc.assets.assets import generate_all_assets_file_list, verify_file

    for group, files in generate_all_assets_file_list().items():
        for file in files:
            if not verify_file(cache / group / file["name"], file["sha3_256"]):
                raise RuntimeError("Offline model/font assets are missing or corrupted")


def force_shutdown() -> None:
    # BabelDOC may be inside a timed font/PDF subprocess when its owner disappears.
    # Reap those children before the private server's hard deadline.
    for child in multiprocessing.active_children():
        child.kill()
        child.join(timeout=1)
    os._exit(0)


def watch_parent(server) -> None:
    # The parent closes this private pipe on disable, shutdown, and process death.
    sys.stdin.buffer.read(1)
    server.should_exit = True
    watchdog = threading.Timer(6, force_shutdown)
    watchdog.daemon = True
    watchdog.start()


async def serve(data: Path, cache: Path, token: str, protocol) -> None:
    import uvicorn

    data.mkdir(parents=True, exist_ok=True)
    os.environ["WENYI_BABELDOC_STATE_DIR"] = str(data)
    configure_assets(cache)
    from wenyi_babeldoc_bridge.pipeline import require_babeldoc
    from wenyi_babeldoc_bridge.server import app

    require_babeldoc()
    from babeldoc.format.pdf.document_il.backend import pdf_creater

    from wenyi_babeldoc_bridge.pdf_workers import save_clean, subset_fonts

    # Keep BabelDOC's process ownership/timeouts, but unpickle lightweight targets.
    # Its original targets import the entire backend (including Hyperscan) in
    # each spawned worker even though these two tasks only need PyMuPDF.
    pdf_creater._subset_fonts_process = subset_fonts
    pdf_creater._save_pdf_clean_process = save_clean
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                PrivateBoundary(app, port, token),
                access_log=False,
                log_config=None,
                timeout_graceful_shutdown=5,
            )
        )
        threading.Thread(target=watch_parent, args=(server,), daemon=True).start()
        task = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started and not task.done():
            await asyncio.sleep(0.01)
        if server.started and not server.should_exit:
            protocol.write(
                json.dumps({"protocol": 1, "port": port, "pid": os.getpid()}) + "\n"
            )
            protocol.flush()
        await task


def main() -> None:
    # Never fork the threaded ONNX/PyMuPDF process during font subsetting.
    # The frozen entry point dispatches spawned children through freeze_support.
    multiprocessing.set_start_method("spawn", force=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("WENYI_BABELDOC_TOKEN")
    if not token:
        parser.error("The Desktop parent must supply WENYI_BABELDOC_TOKEN")
    protocol = sys.stdout
    sys.stdout = sys.stderr
    asyncio.run(
        serve(args.data_dir.resolve(), args.cache_dir.resolve(), token, protocol)
    )


if __name__ == "__main__":
    main()
