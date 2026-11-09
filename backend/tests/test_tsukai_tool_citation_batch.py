from unittest.mock import MagicMock, patch

import pytest

from services.ai.evidence import BufferedBootstrapCitations, DurableCitations


def result(name):
    return {
        "content": "evidence",
        "metadata": {"source_filename": name, "source_id": name, "folder_id": "folder"},
    }


def test_batch_preserves_individual_identity_and_uses_one_rpc():
    registry = DurableCitations("job", "attempt", "owner", "conversation")
    inputs = [result("a.py"), result("b.py"), result("a.py")]
    db = MagicMock()
    db.rpc.return_value.execute.return_value.data = [7, 8, 7]
    with patch("services.ai.evidence.get_supabase_thread_safe", return_value=db):
        assert registry.register_many(inputs) == [7, 8, 7]
    db.rpc.assert_called_once()
    name, args = db.rpc.call_args.args
    assert name == "tsukai_register_citations_batch"
    assert args["p_job_id"] == "job" and args["p_attempt_id"] == "attempt"
    expected = [registry._citation_source(item) for item in inputs]
    assert args["p_citations"] == [
        {"source_key": key, "source": source} for key, source in expected
    ]
    assert all(item["source"]["owner_id"] == "owner" for item in args["p_citations"])


@pytest.mark.parametrize("response", [None, [1], [1, True], [1, "2"], [0, 2], [1, 2, 3]])
def test_invalid_batch_response_does_not_publish_numbers(response):
    db = MagicMock()
    db.rpc.return_value.execute.return_value.data = response
    with patch("services.ai.evidence.get_supabase_thread_safe", return_value=db):
        with pytest.raises(ValueError, match="Invalid citation batch"):
            DurableCitations("job", "attempt", "owner").register_many([result("a"), result("b")])


def test_bootstrap_batch_stays_local_until_its_own_flush():
    registry = BufferedBootstrapCitations("job", "candidate", "owner")
    with patch("services.ai.evidence.get_supabase_thread_safe") as database:
        assert registry.register_many([result("a"), result("b"), result("a")]) == [1, 2, 1]
        assert registry.register_many([]) == []
        database.assert_not_called()
