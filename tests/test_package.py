import importlib
import importlib.metadata
import subprocess
import sys

import pytest

import rate_limiter


def test_top_level_exports_are_importable() -> None:
    for name in rate_limiter.__all__:
        assert hasattr(rate_limiter, name)


def test_version_is_a_string() -> None:
    assert isinstance(rate_limiter.__version__, str)
    assert rate_limiter.__version__


def test_bare_import_does_not_need_optional_extras() -> None:
    code = (
        "import sys, rate_limiter;"
        "bad = {'fastapi', 'starlette', 'redis', 'httpx', 'requests'} & set(sys.modules);"
        "sys.exit(1 if bad else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_version_falls_back_when_the_package_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    try:
        assert importlib.reload(rate_limiter).__version__ == "0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(rate_limiter)
