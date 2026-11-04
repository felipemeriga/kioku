"""Current-turn retrieval must survive resumed harness turns without tool calls."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.ai.chat import prepare_turn, publish_turn
from services.ai.client import ExecutionError, ExecutionResult
from services.ai.evidence import materialize_bootstrap
from services.ai.scope import ExecutionScope


def test_materialization_remint_shares_allocator_and_has_one_truthful_artifact():
    turn = {
        "id": "turn",
        "job_id": "job",
        "owner_id": "owner",
        "request": {
            "folder_ids": ["folder"],
            "metadata": {"bootstrap_namespace": "candidate"},
            "prompt": json.dumps({"current_turn_evidence": "Fresh guide [1]"}),
        },
    }
    trace = {
        "folder_ids": ["folder"],
        "trace": {"origin": "backend_bootstrap", "native_call_id": None},
        "result": "Fresh guide [1]",
    }
    sources, artifacts = {}, {}
    db = MagicMock()
    query = db.table.return_value.select.return_value
    query.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [trace]

    def rpc(name, body):
        assert name == "tsukai_register_citation"
        key = body["p_source_key"]
        sources.setdefault(key, len(sources) + 1)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=sources[key]))

    db.rpc.side_effect = rpc

    def upsert(body, **kwargs):
        artifacts[body["id"]] = body
        return MagicMock()

    db.table.return_value.upsert.side_effect = upsert
    with (
        patch("services.ai.evidence.get_supabase_thread_safe", return_value=db),
        patch(
            "services.ai.evidence.sources_for",
            return_value=[
                {"source_id": "fresh", "owner_id": "owner", "folder_id": "folder", "number": 1}
            ],
        ),
    ):
        materialize_bootstrap(turn, "attempt")
        materialize_bootstrap(turn, "attempt")
    assert sources == {"fresh": 1}
    assert len(artifacts) == 1
    assert next(iter(artifacts.values()))["trace"]["origin"] == "backend_bootstrap"
    assert next(iter(artifacts.values()))["trace"]["native_call_id"] is None
    # Later MCP evidence uses the exact same allocator and cannot overwrite [1].
    assert rpc("tsukai_register_citation", {"p_source_key": "later"}).execute().data == 2


@pytest.mark.parametrize(
    "folders,trace_folders,source_owner,source_folder",
    [
        ([], [], "owner", "folder"),
        (["folder"], ["foreign"], "owner", "folder"),
        (["folder"], ["folder"], "foreign", "folder"),
        (["folder"], ["folder"], "owner", "foreign"),
    ],
)
def test_no_grants_or_foreign_evidence_never_materializes(
    folders, trace_folders, source_owner, source_folder
):
    turn = {
        "id": "turn",
        "job_id": "job",
        "owner_id": "owner",
        "request": {
            "metadata": {"bootstrap_namespace": "candidate"},
            "folder_ids": folders,
            "prompt": '{"current_turn_evidence":"fixture"}',
        },
    }
    db = MagicMock()
    query = db.table.return_value.select.return_value
    query.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"folder_ids": trace_folders}
    ]
    with (
        patch("services.ai.evidence.get_supabase_thread_safe", return_value=db),
        patch(
            "services.ai.evidence.sources_for",
            return_value=[{"owner_id": source_owner, "folder_id": source_folder}],
        ),
    ):
        if folders:
            with pytest.raises(ValueError):
                materialize_bootstrap(turn, "attempt")
        else:
            materialize_bootstrap(turn, "attempt")
    db.rpc.assert_not_called()
    db.table.return_value.upsert.assert_not_called()


def test_prepare_replay_does_not_repeat_lookup():
    turn = {
        "conversation_id": "conversation",
        "request": {
            "metadata": {
                "intent": {
                    "content": "question",
                    "model": "haiku",
                    "mode": "deep",
                    "scope_folder_id": "folder",
                    "scope_filename": "guide.md",
                    "rebuild": False,
                }
            }
        },
    }
    db = MagicMock()
    query = db.table.return_value.select.return_value
    query.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [turn]
    with (
        patch("services.ai.chat.get_supabase_thread_safe", return_value=db),
        patch("services.ai.chat.execute_tool") as search,
    ):
        assert (
            prepare_turn(
                owner_id="owner",
                conversation_id="conversation",
                content="question",
                turn_id="turn",
                model="haiku",
                mode="deep",
                folder_id="folder",
                filename="guide.md",
            )
            == turn
        )
    search.assert_not_called()


def test_resumed_prior_citation_without_current_attempt_evidence_still_rejected():
    turn = {"id": "turn", "job_id": "job", "owner_id": "owner", "request": {"profile": "chat"}}
    with (
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.get_supabase_thread_safe", return_value=MagicMock()),
        patch("services.ai.chat.sources_for", return_value=[]) as sources,
    ):
        with pytest.raises(ExecutionError, match="absent"):
            publish_turn(
                turn,
                ExecutionResult(
                    "job",
                    "Old inherited fact [1]",
                    None,
                    None,
                    "native",
                    "attempt",
                ),
            )
        sources.assert_called_once_with("job", "attempt")


@pytest.mark.parametrize("mode", ["agentic", "deep", "plain"])
def test_preparation_retrieves_current_scoped_evidence_and_plain_stays_unchanged(mode):
    db = MagicMock()
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query
    query.order.return_value = query
    query.execute.return_value.data = []
    db.table.return_value = query
    captured = {}

    def rpc(name, body):
        captured.update(body)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data={"request": body["p_request"]}))

    db.rpc.side_effect = rpc
    with (
        patch("services.ai.chat.get_supabase_thread_safe", return_value=db),
        patch("services.ai.chat.descendant_folder_ids", return_value=["folder"]),
        patch("services.ai.chat.execute_tool", return_value="CURRENT guide fact [1]") as search,
        patch("services.ai.chat.save_trace") as trace,
    ):
        turn = prepare_turn(
            owner_id="owner",
            conversation_id="conversation",
            content="guide?",
            turn_id="turn",
            model="haiku",
            mode=mode,
            folder_id="folder",
            filename="guide.md",
        )
    search.assert_called_once()
    assert search.call_args.kwargs["fast_mode"] is True
    assert search.call_args.kwargs["scope_folder_ids"] == ["folder"]
    assert search.call_args.kwargs["scope_filename"] == "guide.md"
    prompt = json.loads(turn["request"]["prompt"])
    assert (
        prompt["evidence" if mode == "plain" else "current_turn_evidence"]
        == "CURRENT guide fact [1]"
    )
    assert trace.call_args.args[2] == ("plain" if mode == "plain" else "bootstrap")
    if mode != "plain":
        assert trace.call_args.args[4]["origin"] == "backend_bootstrap"
    assert turn["request"]["profile"] == ("completion" if mode == "plain" else "chat")


def test_zero_native_tools_can_publish_only_current_bootstrap_citation():
    turn = {
        "id": "turn",
        "job_id": "job",
        "owner_id": "owner",
        "request": {"profile": "chat", "operation": "rag_agent", "model": "haiku"},
    }
    db = MagicMock()
    query = (
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
    )
    query.order.return_value.execute.return_value.data = [
        {
            "id": "artifact",
            "trace": {"origin": "backend_bootstrap", "native_call_id": None, "sources": []},
        }
    ]
    db.rpc.return_value.execute.return_value.data = "message"
    fresh = [{"number": 1, "file": "current-guide.md", "owner_id": "owner"}]
    with (
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.get_supabase_thread_safe", return_value=db),
        patch("services.ai.chat.sources_for", return_value=fresh),
        patch("services.ai.chat.client_for", return_value=MagicMock()),
        patch("services.ai.chat.record_job_usage", return_value=[]),
    ):
        assert (
            publish_turn(
                turn,
                ExecutionResult(
                    "job", "Current guide fact [1]", None, None, "resumed-native", "attempt"
                ),
            )
            == "message"
        )
    args = db.rpc.call_args.args
    assert args[0] == "tsukai_commit_chat_turn"
    assert args[1]["p_citations"] == fresh
    assert args[1]["p_debug"]["tool_calls"][0]["origin"] == "backend_bootstrap"


@pytest.mark.parametrize("conflicting_scope", [False, True])
def test_concurrent_candidates_are_isolated_and_only_accepted_namespace_materializes(
    conflicting_scope,
):
    """Two preparations pass the precheck before either wins immutable admission."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    barrier, lock = Barrier(2), Lock()
    candidates, accepted = {}, []
    db = MagicMock()
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query
    query.order.return_value = query
    query.execute.return_value.data = []
    db.table.return_value = query

    def search(*args, **kwargs):
        registry = kwargs["citations"]
        assert registry.job_id not in {"turn", "job"}
        candidates[registry.job_id] = kwargs["scope_folder_ids"][0]
        barrier.wait(timeout=5)
        return f"{registry.job_id} current evidence [1]"

    def rpc(name, body):
        with lock:
            if not accepted:
                accepted.append(
                    {
                        "id": "turn",
                        "owner_id": "owner",
                        "job_id": "job",
                        "request": body["p_request"],
                    }
                )
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=accepted[0]))

    db.rpc.side_effect = rpc

    def prepare(folder):
        return prepare_turn(
            owner_id="owner",
            conversation_id="conversation",
            content="guide?",
            turn_id="turn",
            model="haiku",
            mode="deep",
            folder_id=folder,
            filename=None,
        )

    with (
        patch("services.ai.chat.get_supabase_thread_safe", return_value=db),
        patch(
            "services.ai.chat.descendant_folder_ids", side_effect=lambda sb, folder, owner: [folder]
        ),
        patch("services.ai.chat.execute_tool", side_effect=search),
        patch("services.ai.chat.save_trace") as save,
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(prepare, ["folder", "foreign" if conflicting_scope else "folder"]))
    assert len(candidates) == 2
    staged = {
        call.args[1]: {"folder_ids": call.args[3], "trace": call.args[4], "result": call.args[5]}
        for call in save.call_args_list
    }
    winner = accepted[0]
    namespace = winner["request"]["metadata"]["bootstrap_namespace"]
    assert namespace in json.loads(winner["request"]["prompt"])["current_turn_evidence"]
    db2 = MagicMock()
    q = db2.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
    q.execute.return_value.data = [staged[namespace]]
    db2.rpc.return_value.execute.return_value.data = 1
    source = {
        "source_id": namespace,
        "number": 1,
        "owner_id": "owner",
        "folder_id": candidates[namespace],
    }
    with (
        patch("services.ai.evidence.get_supabase_thread_safe", return_value=db2),
        patch("services.ai.evidence.sources_for", return_value=[source]) as sources,
    ):
        materialize_bootstrap(winner, "attempt")
    sources.assert_called_once_with(namespace, "bootstrap")
    assert db2.rpc.call_args.args[1]["p_source_key"] == namespace
    assert db2.table.return_value.upsert.call_args.args[0]["result"] == staged[namespace]["result"]
