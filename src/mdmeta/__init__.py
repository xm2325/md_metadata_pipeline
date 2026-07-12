"""MD literature metadata pipeline."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("md-metadata-pipeline")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.11.0"


def user_agent(component: str) -> str:
    """Return the versioned user agent used for external scientific services."""

    return f"md-metadata-pipeline/{__version__} {component}"
