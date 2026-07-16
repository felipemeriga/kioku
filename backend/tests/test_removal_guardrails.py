"""Guardrails for the github-sync removal. These MUST stay green through
every removal task: the replace_briefing save path (Plan A depends on it)
and doc-folder summarization must survive."""
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


def test_app_imports_and_doc_summary_entrypoint_present():
    main = importlib.import_module("main")
    assert main.app is not None
    # Doc-folder summarization entrypoint stays.
    from services.folder_summary import generate_folder_summary
    assert callable(generate_folder_summary)
