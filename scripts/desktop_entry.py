"""PyInstaller entry point; keep the AGPL runtime in its own distribution."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from wenyi_babeldoc_bridge.desktop_runtime import main

    main()
