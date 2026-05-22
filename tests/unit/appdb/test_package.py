"""Tests that the appdb package is importable and self-describing.

``appdb`` owns ``app.db`` — the accounts/config database, separate from the
search index. It must import without pulling in ``store``, ``search``, or any
daemon package, because Wave 4 needs the OCR and classifier daemons (which are
barred from ``store``) to read ``app.db`` config through this package.
"""

from __future__ import annotations

import importlib


def test_appdb_package_imports() -> None:
    """The appdb package imports cleanly."""
    module = importlib.import_module("appdb")
    assert module is not None


def test_appdb_package_has_a_docstring() -> None:
    """The appdb package documents its purpose."""
    module = importlib.import_module("appdb")
    assert module.__doc__ is not None
    assert module.__doc__.strip() != ""
