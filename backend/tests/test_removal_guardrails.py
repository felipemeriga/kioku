"""Guardrails for the briefing save path. The replace_briefing helpers that
repo briefings depend on must survive future refactors. (The non-repo folder
summary engine was removed — only repos have briefings now.)"""

import importlib


def test_briefing_schema_helpers_importable():
    # The schema/persist helpers replace_briefing relies on must remain.
    mod = importlib.import_module("routes.briefing")
    assert hasattr(mod, "replace_briefing")
    assert hasattr(mod, "_persist_sections")
    # SECTION_KEYS + new_section + empty_briefing must be importable from
    # wherever they end up living (Task 2 may move them).
    from routes.briefing import SECTION_KEYS

    assert "overview" in SECTION_KEYS and "activity" in SECTION_KEYS


def test_app_imports():
    main = importlib.import_module("main")
    assert main.app is not None
