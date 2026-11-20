#!/usr/bin/env python3
"""HTTP service calling BabelDOC in a process separate from Wenyi.

Run from the dedicated Wenyi runtime or bridge development environment:

  .venv-wenyi/bin/python -m uvicorn wenyi_babeldoc_bridge.server:app \\
      --host 127.0.0.1 --port 8765

API:
  POST /extract   multipart: file=PDF, pages=optional
  POST /fillback  json: {session_id, translations:{id: text}}
  GET  /session/{id}
  DELETE /session/{id}
  GET  /health
"""

from __future__ import annotations

import gc
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import uuid
from _thread import LockType
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import anyio
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.types import Message, Receive, Scope, Send

# Support running from a source checkout without installation.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from wenyi_babeldoc_bridge import __version__  # noqa: E402
from wenyi_babeldoc_bridge.pipeline import (  # noqa: E402
    ExtractSession,
    extract_to_session,
    fillback_session,
    restore_session_with_docs,
)

app = FastAPI(title="Wenyi BabelDOC Bridge", version=__version__)

_LOCK = threading.Lock()
_EXTRACT_LOCK = threading.Lock()
_SESSIONS: dict[str, ExtractSession] = {}
_CLEANUP_BUSY = "session cleanup failed; retry deletion"
_BASE = Path(
    os.environ.get(
        "WENYI_BABELDOC_STATE_DIR",
        str(Path(tempfile.gettempdir()) / "wenyi-babeldoc-bridge"),
    )
).expanduser()
_BASE.mkdir(parents=True, exist_ok=True)


@dataclass
class _SessionUse:
    deleting: bool
    users: int = 0
    render: LockType = field(default_factory=threading.Lock)


_SESSION_USES: dict[str, _SessionUse] = {}


@contextmanager
def _use_session(session_id: str, *, deleting: bool = False) -> Iterator[_SessionUse]:
    """Pin the session through delivery; only deletion needs exclusive access."""
    with _LOCK:
        use = _SESSION_USES.get(session_id)
        if use is None:
            use = _SESSION_USES[session_id] = _SessionUse(deleting)
        elif deleting:
            raise HTTPException(status_code=503, detail=_CLEANUP_BUSY)
        elif use.deleting:
            raise HTTPException(status_code=404, detail="session not found")
        use.users += 1
    try:
        yield use
    finally:
        with _LOCK:
            use.users -= 1
            if not use.users:
                del _SESSION_USES[session_id]


class _Delivery:
    """Transfer cleanup from the render worker to the ASGI request, if still alive."""

    def __init__(self):
        self._lock = threading.Lock()
        self._resources: ExitStack | None = ExitStack()

    def take(self, resources: ExitStack) -> None:
        with self._lock:
            if self._resources is not None:
                self._resources = resources.pop_all()

    def close(self) -> None:
        with self._lock:
            resources, self._resources = self._resources, None
        if resources is not None:
            resources.close()


class _DeliveryDisconnected(Exception):
    pass


class _FillbackResponse(FileResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        disconnected = False
        sending: anyio.CancelScope | None = None

        def stop_delivery() -> None:
            nonlocal disconnected
            disconnected = True
            if sending is not None:
                sending.cancel()

        async def watch_disconnect() -> None:
            while (await receive())["type"] != "http.disconnect":
                pass
            stop_delivery()

        async def send_connected(message: Message) -> None:
            nonlocal sending
            if not disconnected:
                # Interrupt a blocked send, not FileResponse's file operations.
                # Let FileResponse unwind and close the file before cleanup.
                with anyio.CancelScope() as sending:
                    await send(message)
                sending = None
            if disconnected:
                raise _DeliveryDisconnected

        async def wait_for_stream() -> Message:
            # Some Starlette releases also listen in FileResponse. Only our
            # watcher should read from the actual ASGI receive channel.
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

        failure: Exception | None = None

        async def stream() -> None:
            nonlocal failure
            # A cancelled ASGI task must wait for an in-progress open/read/close
            # to finish. Only the send is interruptible, even on older Starlette.
            with anyio.CancelScope(shield=True):
                try:
                    await super(_FillbackResponse, self).__call__(
                        scope, wait_for_stream, send_connected
                    )
                except _DeliveryDisconnected:
                    pass
                except Exception as error:
                    failure = error
                finally:
                    group.cancel_scope.cancel()

        async with anyio.create_task_group() as group:
            group.start_soon(watch_disconnect)
            group.start_soon(stream)
            try:
                await anyio.sleep_forever()
            finally:
                stop_delivery()
        if failure is not None:
            raise failure


class _FillbackRoute(APIRoute):
    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        delivery = _Delivery()
        # Keep ownership until ASGI returns, not just until the sync endpoint
        # returns. Also cover cancellation before FileResponse is ever called.
        scope["wenyi.fillback.delivery"] = delivery
        if "http.response.pathsend" in scope.get("extensions", {}):
            # Don't hand the temporary path off to a server for deferred opening.
            scope = {**scope, "extensions": dict(scope["extensions"])}
            del scope["extensions"]["http.response.pathsend"]
        try:
            await super().handle(scope, receive, send)
        finally:
            delivery.close()


_fillback_router = APIRouter(route_class=_FillbackRoute)


def _session_dir(session_id: str) -> Path | None:
    if re.fullmatch(r"[0-9a-f]{32}", session_id) is None:
        return None
    return _BASE / session_id


def _durable_session_ids() -> set[str]:
    result: set[str] = set()
    for path in _BASE.iterdir():
        if not path.is_dir() or _session_dir(path.name) != path:
            continue
        if (path / "session.json").is_file() or (
            (path / "styles_and_formulas.json").is_file()
            and (path / "paragraphs.json").is_file()
        ):
            result.add(path.name)
    return result


def _get_or_restore_session(
    session_id: str, *, for_fillback: bool = False
) -> tuple[ExtractSession | None, object | None]:
    """Called with the session in use and its render lock held."""
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if session is not None:
        return session, None

    out_dir = _session_dir(session_id)
    if out_dir is None or not out_dir.is_dir():
        return None, None
    try:
        session, docs = restore_session_with_docs(
            session_id=session_id, out_dir=out_dir
        )
    except FileNotFoundError:
        return None, None
    with _LOCK:
        _SESSIONS[session_id] = session
    # Other requests can see the metadata but never this mutable graph.
    return session, docs if for_fillback else None


class FillbackRequest(BaseModel):
    session_id: str
    translations: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, dict] | None = None
    rows: dict[str, list[dict]] | None = None


@app.get("/health")
def health():
    with _LOCK:
        loaded = set(_SESSIONS)
    durable = _durable_session_ids()
    return {
        "ok": True,
        "sessions": len(loaded | durable),
        "loaded_sessions": len(loaded),
        "durable_sessions": len(durable),
        "capabilities": [
            "annotation-alignment-v1",
            "annotation-best-effort-v1",
            "protected-objects-v1",
            "protected-object-omission-v1",
            "toc-rows-v1",
        ],
    }


@app.get("/session/{session_id}")
def get_session(session_id: str):
    with _use_session(session_id) as use, use.render:
        try:
            session, _ = _get_or_restore_session(session_id)
        except Exception as error:
            raise HTTPException(
                status_code=500, detail=f"session restore failed: {error}"
            ) from error
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session_id": session.session_id,
        "pdf_path": session.pdf_path,
        "pages_spec": session.pages_spec,
        "paragraph_count": len(session.paragraphs.paragraphs),
        "paragraphs": session.paragraphs.to_dict(for_client=True),
        "restored": session.restored,
    }


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    with _use_session(session_id, deleting=True):
        with _LOCK:
            session = _SESSIONS.get(session_id)
        out_dir = _session_dir(session_id)
        if session is None and (out_dir is None or not out_dir.is_dir()):
            raise HTTPException(status_code=404, detail="session not found")
        directory = session.out_dir if session is not None else out_dir
        assert directory is not None
        # BabelDOC's writer leaves unreachable PyMuPDF document/page cycles.
        # Release their native file handles before removing files on Windows.
        gc.collect()
        try:
            shutil.rmtree(directory)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise HTTPException(status_code=503, detail=_CLEANUP_BUSY) from error
        with _LOCK:
            _SESSIONS.pop(session_id, None)
    return {"ok": True, "session_id": session_id}


@app.post("/extract")
def extract(
    file: UploadFile = File(...),
    pages: str | None = Form(default=None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    session_id = uuid.uuid4().hex
    out_dir = _BASE / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / (Path(file.filename).name or "input.pdf")

    try:
        # UploadFile is already spooled. Copy it without allocating the whole PDF,
        # and let FastAPI's sync endpoint run this blocking pipeline off the event loop.
        with pdf_path.open("wb") as output:
            shutil.copyfileobj(file.file, output, length=256 * 1024)
        # Keep the previous single-extraction budget for model/IL memory.
        with _EXTRACT_LOCK:
            session = extract_to_session(
                session_id=session_id,
                pdf_path=pdf_path,
                pages_spec=pages or None,
                out_dir=out_dir,
            )
    except Exception as error:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(error)) from error

    with _LOCK:
        _SESSIONS[session_id] = session

    return {
        "session_id": session_id,
        "pages_spec": pages,
        "paragraph_count": len(session.paragraphs.paragraphs),
        "paragraphs": session.paragraphs.to_dict(for_client=True),
    }


@_fillback_router.post("/fillback")
def fillback(body: FillbackRequest, request: Request):
    delivery: _Delivery = request.scope["wenyi.fillback.delivery"]
    with ExitStack() as resources:
        use = resources.enter_context(_use_session(body.session_id))
        with use.render:
            try:
                session, pristine_docs = _get_or_restore_session(
                    body.session_id, for_fillback=True
                )
            except Exception as error:
                raise HTTPException(
                    status_code=500, detail=f"session restore failed: {error}"
                ) from error
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            if not body.translations and session.paragraphs.paragraphs:
                raise HTTPException(status_code=400, detail="translations empty")

            statistics = {}
            try:
                render_dir = Path(
                    resources.enter_context(
                        tempfile.TemporaryDirectory(
                            dir=session.out_dir, prefix=".fillback-"
                        )
                    )
                )
                out_pdf = fillback_session(
                    session,
                    body.translations,
                    body.annotations,
                    rows=body.rows,
                    statistics=statistics,
                    _pristine_docs=pristine_docs,
                    _render_dir=render_dir,
                )
                # Retain the last successful render's session diagnostics at
                # their documented paths. Never serve a shared session file.
                for name in (
                    "translations.json",
                    "inject_stats.json",
                    "annotation_stats.json",
                ):
                    os.replace(render_dir / name, session.out_dir / name)
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            except Exception as error:
                raise HTTPException(status_code=500, detail=str(error)) from error

        response = _FillbackResponse(
            path=out_pdf,
            media_type="application/pdf",
            filename=f"{body.session_id}.mono.pdf",
            headers={
                "X-Wenyi-PDF-Annotation-Stats": json.dumps(
                    statistics, separators=(",", ":")
                )
            },
        )
        delivery.take(resources)
        return response


app.include_router(_fillback_router)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "wenyi_babeldoc_bridge.server:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":
    main()
