"""Event dispatch is idempotent on event.id."""

from obol_ledger import sample_data


def test_settlement_posts_once(dispatcher, journal):
    env = sample_data.settled_envelope("evt_settled_A")

    first = dispatcher.dispatch(env)
    assert first.status == "posted"
    assert len(journal) == 1

    # Redeliver the same event id.
    second = dispatcher.dispatch(env)
    assert second.status == "duplicate"
    assert second.result_id == first.result_id
    # No new journal entry appended.
    assert len(journal) == 1


def test_unconsumed_event_is_ignored(dispatcher, journal):
    env = sample_data.settled_envelope("evt_auth_1")
    env = env.model_copy(update={"type": "payment.authorized"})
    result = dispatcher.dispatch(env)
    assert result.status == "ignored"
    assert len(journal) == 0


def test_settle_then_refund_dispatch(dispatcher, journal):
    dispatcher.dispatch(sample_data.settled_envelope("evt_s1"))
    result = dispatcher.dispatch(sample_data.refund_envelope("evt_r1"))
    assert result.status == "posted"
    assert len(journal) == 2

    # Refund replay is a no-op.
    replay = dispatcher.dispatch(sample_data.refund_envelope("evt_r1"))
    assert replay.status == "duplicate"
    assert len(journal) == 2
