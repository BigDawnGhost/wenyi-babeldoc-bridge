"""Session deletion releases native file cycles and never reports failed cleanup as OK."""

import gc
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from wenyi_babeldoc_bridge import server


class SessionCleanupTests(unittest.TestCase):
    def test_delete_collects_unreachable_native_file_cycles(self):
        class NativeDocument:
            def __init__(self, stream):
                self.stream = stream
                self.cycle = self

            def __del__(self):
                self.stream.close()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "a" * 32
            directory = root / session_id
            directory.mkdir()
            stream = (directory / "synthetic.pdf").open("wb")
            remove = shutil.rmtree

            def remove_after_release(path, **kwargs):
                self.assertTrue(stream.closed)
                remove(path, **kwargs)

            was_enabled = gc.isenabled()
            gc.disable()
            try:
                native = NativeDocument(stream)
                del native
                with (
                    patch.object(server, "_BASE", root),
                    patch.object(
                        server,
                        "_SESSIONS",
                        {session_id: SimpleNamespace(out_dir=directory)},
                    ),
                    patch.object(
                        server.shutil, "rmtree", side_effect=remove_after_release
                    ),
                ):
                    self.assertTrue(server.delete_session(session_id)["ok"])
                    self.assertNotIn(session_id, server._SESSIONS)
                    self.assertFalse(directory.exists())
            finally:
                gc.collect()
                if was_enabled:
                    gc.enable()

    def test_failed_cleanup_keeps_loaded_session_for_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "b" * 32
            session = SimpleNamespace(out_dir=root / session_id)
            with (
                patch.object(server, "_BASE", root),
                patch.object(server, "_SESSIONS", {session_id: session}),
                patch.object(
                    server.shutil, "rmtree", side_effect=PermissionError("busy")
                ),
            ):
                with self.assertRaises(HTTPException) as raised:
                    server.delete_session(session_id)
                self.assertEqual(raised.exception.status_code, 503)
                self.assertIs(server._SESSIONS[session_id], session)
