"""Independent AGPL BabelDOC HTTP bridge for Wenyi."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("wenyi-babeldoc-bridge")
except PackageNotFoundError:
    # Source-only probes can run without an installed distribution.
    __version__ = "0+unknown"
