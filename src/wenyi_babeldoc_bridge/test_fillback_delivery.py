"""Exercise HTTP delivery separately from rendering, without timing sleeps."""

import asyncio
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from wenyi_babeldoc_bridge import server

TIMEOUT = 15


async def post_fillback(payload, *, before_send=None, disconnect=None, spec="2.4"):
    """Drive ASGI directly so a response can pause before Starlette opens its PDF."""
    messages = []
    body = json.dumps(payload).encode()
    sent_input = False

    async def receive():
        nonlocal sent_input
        if not sent_input:
            sent_input = True
            return {"type": "http.request", "body": body}
        if disconnect is None:
            await asyncio.Future()
        else:
            await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if before_send is not None:
            await before_send(message)
        messages.append(message)

    await server.app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": spec},
            "method": "POST",
            "scheme": "http",
            "path": "/fillback",
            "raw_path": b"/fillback",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "extensions": {"http.response.pathsend": {}},
        },
        receive,
        send,
    )
    return messages


def response_body(messages):
    return b"".join(
        message["body"]
        for message in messages
        if message["type"] == "http.response.body"
    )


class FillbackDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.session_id = "a" * 32
        self.other_id = "b" * 32
        self.folder = self.root / self.session_id
        sessions = {}
        for key in (self.session_id, self.other_id):
            directory = self.root / key
            directory.mkdir()
            sessions[key] = SimpleNamespace(
                out_dir=directory, paragraphs=SimpleNamespace(paragraphs=["0:0"])
            )
        for name, value in (("_BASE", self.root), ("_SESSIONS", sessions)):
            override = patch.object(server, name, value)
            override.start()
            self.addCleanup(override.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://bridge"
        )
        self.addAsyncCleanup(self.client.aclose)

    def payload(self, text="A", *, session_id=None):
        return {
            "session_id": session_id or self.session_id,
            "translations": {"0:0": text},
        }

    def fake_render(
        self, session, translations, annotations, *, statistics, _render_dir, **kw
    ):
        text = translations["0:0"]
        self.assertEqual(_render_dir.parent, session.out_dir)
        statistics["render"] = text
        for name in ("translations.json", "inject_stats.json", "annotation_stats.json"):
            (_render_dir / name).write_text(
                json.dumps({"render": text}), encoding="utf-8"
            )
        (_render_dir / "native.mono.pdf").write_bytes(text.encode())
        pdf = _render_dir / "fillback.mono.pdf"
        pdf.write_bytes(text.encode())
        return pdf

    async def delete(self):
        return await asyncio.wait_for(
            self.client.delete(f"/session/{self.session_id}"), TIMEOUT
        )

    def assert_clean(self):
        self.assertFalse(list(self.folder.glob(".fillback-*")))
        self.assertFalse(server._SESSION_USES)

    async def test_overlap_and_delayed_open_return_each_requests_pdf_and_stats(self):
        rendering_a = asyncio.Event()
        queued_b = asyncio.Event()
        delivered_headers_a = asyncio.Event()
        finish_a = asyncio.Event()
        finish_render_a = threading.Event()
        loop = asyncio.get_running_loop()
        rendered = []
        use_session = server._use_session

        @contextmanager
        def track_use(session_id, *, deleting=False):
            with use_session(session_id, deleting=deleting) as use:
                if session_id == self.session_id and use.users == 2:
                    loop.call_soon_threadsafe(queued_b.set)
                yield use

        def render(session, translations, *args, **kw):
            text = translations["0:0"]
            pdf = self.fake_render(session, translations, *args, **kw)
            rendered.append(pdf)
            if text == "A":
                loop.call_soon_threadsafe(rendering_a.set)
                self.assertTrue(finish_render_a.wait(TIMEOUT))
            return pdf

        async def delay_a(message):
            if message["type"] == "http.response.start":
                delivered_headers_a.set()
                await finish_a.wait()

        with (
            patch.object(server, "_use_session", track_use),
            patch.object(server, "fillback_session", side_effect=render),
        ):
            a = asyncio.create_task(post_fillback(self.payload(), before_send=delay_a))
            b = None
            try:
                await asyncio.wait_for(rendering_a.wait(), TIMEOUT)
                self.assertEqual((await self.delete()).status_code, 503)
                self.assertTrue(rendered[0].is_file())
                b = asyncio.create_task(post_fillback(self.payload("BBBB")))
                await asyncio.wait_for(queued_b.wait(), TIMEOUT)
                # A is still rendering; the same-session B is queued, but C can run.
                c = await asyncio.wait_for(
                    post_fillback(self.payload("C", session_id=self.other_id)), TIMEOUT
                )
                self.assertEqual(response_body(c), b"C")
                self.assertEqual(len(rendered), 2)
                finish_render_a.set()
                await asyncio.wait_for(delivered_headers_a.wait(), TIMEOUT)
                b_messages = await asyncio.wait_for(b, TIMEOUT)
                self.assertEqual(response_body(b_messages), b"BBBB")
                self.assertEqual(len(list(self.folder.glob(".fillback-*"))), 1)
                self.assertEqual((await self.delete()).status_code, 503)
                self.assertTrue(rendered[0].is_file())
                self.assertEqual(
                    json.loads((self.folder / "annotation_stats.json").read_bytes()),
                    {"render": "BBBB"},
                )
            finally:
                finish_render_a.set()
                finish_a.set()
                a_messages = await asyncio.wait_for(a, TIMEOUT)
                if b is not None:
                    await asyncio.wait_for(b, TIMEOUT)
        self.assertEqual(response_body(a_messages), b"A")
        for messages, text in ((a_messages, b"A"), (b_messages, b"BBBB")):
            self.assertEqual(messages[0]["status"], 200)
            headers = dict(messages[0]["headers"])
            self.assertEqual(headers[b"content-type"], b"application/pdf")
            self.assertIn(
                f"{self.session_id}.mono.pdf".encode(), headers[b"content-disposition"]
            )
            self.assertEqual(headers[b"content-length"], str(len(text)).encode())
            self.assertEqual(
                json.loads(headers[b"x-wenyi-pdf-annotation-stats"]),
                {"render": text.decode()},
            )
        self.assert_clean()
        self.assertEqual((await self.delete()).status_code, 200)
        self.assertFalse(self.folder.exists())
        self.assertEqual(
            (await self.client.post("/fillback", json=self.payload())).status_code, 404
        )

    async def test_failed_send_task_cancel_and_disconnect_release_open_output(self):
        for mode in (
            "send_error",
            "task_cancel",
            "disconnect",
            "disconnect_legacy_asgi",
        ):
            with self.subTest(mode=mode):
                sending = asyncio.Event()
                disconnect = asyncio.Event()

                async def block_body(message):
                    if message["type"] == "http.response.body":
                        sending.set()
                        if mode == "send_error":
                            raise OSError("send failed")
                        await asyncio.Future()

                with patch.object(
                    server, "fillback_session", side_effect=self.fake_render
                ):
                    request = asyncio.create_task(
                        post_fillback(
                            self.payload(),
                            before_send=block_body,
                            disconnect=disconnect,
                            spec="2.3" if mode == "disconnect_legacy_asgi" else "2.4",
                        )
                    )
                    try:
                        await asyncio.wait_for(sending.wait(), TIMEOUT)
                        if mode == "send_error":
                            with self.assertRaisesRegex(OSError, "send failed"):
                                await asyncio.wait_for(request, TIMEOUT)
                        elif mode == "task_cancel":
                            request.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await asyncio.wait_for(request, TIMEOUT)
                        else:
                            self.assertEqual((await self.delete()).status_code, 503)
                            disconnect.set()
                            await asyncio.wait_for(request, TIMEOUT)
                    finally:
                        if not request.done():
                            request.cancel()
                            await asyncio.gather(request, return_exceptions=True)
                self.assert_clean()
        self.assertEqual((await self.delete()).status_code, 200)

    async def test_cancel_during_file_open_waits_for_file_io_before_cleanup(self):
        opening = asyncio.Event()
        resume_open = asyncio.Event()
        open_file = server.anyio.open_file

        async def delayed_open(path, *args, **kwargs):
            opening.set()
            await resume_open.wait()
            self.assertTrue(path.is_file())
            return await open_file(path, *args, **kwargs)

        with (
            patch.object(server, "fillback_session", side_effect=self.fake_render),
            patch.object(server.anyio, "open_file", side_effect=delayed_open),
        ):
            request = asyncio.create_task(post_fillback(self.payload()))
            try:
                await asyncio.wait_for(opening.wait(), TIMEOUT)
                request.cancel()
                self.assertEqual((await self.delete()).status_code, 503)
                self.assertFalse(request.done())
            finally:
                resume_open.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(request, TIMEOUT)
        self.assert_clean()
        self.assertEqual((await self.delete()).status_code, 200)

    async def test_failed_render_removes_partial_artifacts_and_keeps_session(self):
        def fail_render(*args, _render_dir, **kw):
            self.fake_render(*args, _render_dir=_render_dir, **kw)
            raise RuntimeError("render failed")

        with patch.object(server, "fillback_session", side_effect=fail_render):
            result = await self.client.post("/fillback", json=self.payload())
        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.json(), {"detail": "render failed"})
        self.assertFalse((self.folder / "translations.json").exists())
        self.assert_clean()
        self.assertEqual((await self.delete()).status_code, 200)

    async def test_cancel_before_response_handoff_leaves_cleanup_with_worker(self):
        started = asyncio.Event()
        released = asyncio.Event()
        resume = threading.Event()
        loop = asyncio.get_running_loop()
        use_session = server._use_session

        @contextmanager
        def track_use(session_id, *, deleting=False):
            try:
                with use_session(session_id, deleting=deleting) as use:
                    yield use
            finally:
                if not deleting:
                    loop.call_soon_threadsafe(released.set)

        def render(*args, **kw):
            pdf = self.fake_render(*args, **kw)
            loop.call_soon_threadsafe(started.set)
            self.assertTrue(resume.wait(TIMEOUT))
            self.assertTrue(pdf.is_file())
            return pdf

        with (
            patch.object(server, "_use_session", track_use),
            patch.object(server, "fillback_session", side_effect=render),
        ):
            request = asyncio.create_task(post_fillback(self.payload()))
            try:
                await asyncio.wait_for(started.wait(), TIMEOUT)
                request.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(request, TIMEOUT)
                self.assertEqual((await self.delete()).status_code, 503)
                self.assertEqual(len(list(self.folder.glob(".fillback-*"))), 1)
            finally:
                resume.set()
                await asyncio.wait_for(released.wait(), TIMEOUT)
        self.assert_clean()
        self.assertEqual((await self.delete()).status_code, 200)
