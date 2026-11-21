"""Tests that the appdb package is importable and documented."""

from __future__ import annotations

import importlib


def test_appdb_package_imports() -> None:
    module = importlib.import_module("appdb")
    assert module is not None


def test_appdb_package_has_a_docstring() -> None:
    module = importlib.import_module("appdb")
    assert module.__doc__ is not None
    assert module.__doc__.strip() != ""
