"""PyInstaller entry point; keep the AGPL runtime in its own distribution."""

import faulthandler
import multiprocessing
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    diagnostics = os.environ.get("WENYI_BABELDOC_DIAGNOSTICS_DIR")
    if diagnostics:
        # Spawned Windows workers may not inherit usable standard error handles.
        directory = Path(diagnostics)
        directory.mkdir(parents=True, exist_ok=True)
        sys.stderr = (directory / f"{os.getpid()}.log").open("w", encoding="utf-8")
        print(f"Frozen process started: {sys.argv!r}", file=sys.stderr, flush=True)
        faulthandler.enable()
        faulthandler.dump_traceback_later(30, repeat=True)
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes

        # Every spawned worker needs the same native search paths as the server;
        # importing NumPy first must not be necessary to load another wheel.
        ctypes.windll.kernel32.SetErrorMode(0x8003)
        dll_directories = [
            os.add_dll_directory(str(path))
            for path in Path(sys._MEIPASS).glob("*.libs")
            if path.is_dir()
        ]
    multiprocessing.freeze_support()
    from wenyi_babeldoc_bridge.desktop_runtime import main

    main()
