import pytest

from app.session_registry import SessionConflictError, SessionRegistry


def test_new_session_then_reconnect_within_grace():
    reg = SessionRegistry()
    first = reg.try_claim(None, owner="ws1")
    assert not first.is_reconnect
    reg.release(first.session_id, first.generation)

    again = reg.try_claim(first.session_id, owner="ws2")
    assert again.is_reconnect
    assert again.superseded_owner is None


def test_different_session_while_connected_conflicts():
    reg = SessionRegistry()
    reg.try_claim("a", owner="ws1")
    with pytest.raises(SessionConflictError):
        reg.try_claim("b", owner="ws2")


def test_same_session_while_still_connected_takes_over():
    reg = SessionRegistry()
    old = reg.try_claim("a", owner="ws1")
    new = reg.try_claim("a", owner="ws2")
    assert new.is_reconnect
    assert new.superseded_owner == "ws1"
    assert new.generation > old.generation


def test_stale_release_does_not_disconnect_the_new_owner():
    reg = SessionRegistry()
    old = reg.try_claim("a", owner="ws1")
    reg.try_claim("a", owner="ws2")
    reg.release("a", old.generation)  # old socket's handler finishing late
    with pytest.raises(SessionConflictError):
        reg.try_claim("b")  # slot must still be held by ws2


def test_new_session_evicts_released_one():
    reg = SessionRegistry()
    first = reg.try_claim("a")
    reg.release("a", first.generation)
    second = reg.try_claim("b")
    assert second.evicted_session_id == "a"
