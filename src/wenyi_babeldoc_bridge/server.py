#!/usr/bin/env python3
"""Minimal same-process BabelDOC bridge for Wenyi.

Run inside the isolated babeldoc venv:

  /tmp/wenyi-babeldoc-venv/bin/python -m uvicorn wenyi_babeldoc_bridge.server:app \\
      --app-dir experiments --host 127.0.0.1 --port 8765

API:
  POST /extract   multipart: file=PDF, pages=optional
  POST /fillback  json: {session_id, translations:{id: text}}
  GET  /session/{id}
  DELETE /session/{id}
  GET  /health
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# Support running from a source checkout without installation.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from wenyi_babeldoc_bridge.pipeline import (  # noqa: E402
    ExtractSession,
    extract_to_session,
    fillback_session,
)

app = FastAPI(title="Wenyi BabelDOC Bridge", version="0.1.0")

_LOCK = threading.Lock()
_SESSIONS: dict[str, ExtractSession] = {}
_BASE = Path(tempfile.gettempdir()) / "wenyi-babeldoc-bridge"
_BASE.mkdir(parents=True, exist_ok=True)


class FillbackRequest(BaseModel):
    session_id: str
    translations: dict[str, str] = Field(default_factory=dict)


@app.get("/health")
def health():
    with _LOCK:
        n = len(_SESSIONS)
    return {"ok": True, "sessions": n}


@app.get("/session/{session_id}")
def get_session(session_id: str):
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session_id": session.session_id,
        "pdf_path": session.pdf_path,
        "pages_spec": session.pages_spec,
        "paragraph_count": len(session.paragraphs.paragraphs),
        "paragraphs": session.paragraphs.to_dict(),
    }


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    with _LOCK:
        session = _SESSIONS.pop(session_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    shutil.rmtree(session.out_dir, ignore_errors=True)
    return {"ok": True, "session_id": session_id}


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    pages: str | None = Form(default=None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    session_id = uuid.uuid4().hex
    out_dir = _BASE / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / (Path(file.filename).name or "input.pdf")
    pdf_path.write_bytes(await file.read())

    try:
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
        "paragraphs": session.paragraphs.to_dict(),
    }


@app.post("/fillback")
def fillback(body: FillbackRequest):
    with _LOCK:
        session = _SESSIONS.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if not body.translations:
        raise HTTPException(status_code=400, detail="translations empty")

    try:
        out_pdf = fillback_session(session, body.translations)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return FileResponse(
        path=out_pdf,
        media_type="application/pdf",
        filename=f"{body.session_id}.mono.pdf",
    )


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
