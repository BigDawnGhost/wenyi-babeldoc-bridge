"""PyInstaller entry point; keep the AGPL runtime in its own distribution."""

import faulthandler
import multiprocessing
import os

if __name__ == "__main__":
    if os.environ.get("WENYI_BABELDOC_DIAGNOSTICS") == "1":
        faulthandler.enable()
        faulthandler.dump_traceback_later(30, repeat=True)
    multiprocessing.freeze_support()
    from wenyi_babeldoc_bridge.desktop_runtime import main

    main()
