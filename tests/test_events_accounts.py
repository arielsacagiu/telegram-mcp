"""Account attribution for the event-driven incoming-message tools."""

import json
from types import SimpleNamespace

import pytest
from telethon.tl.types import User

from telegram_mcp.tools import events


@pytest.fixture(autouse=True)
def _clear_pending():
    # The activity Event binds to whichever loop first awaits it. Production has
    # one loop for the process lifetime (asyncio.run), but each async test gets a
    # fresh one, so drop the cached Event along with the pending map.
    events._pending_msgs.clear()
    events._activity_event = None
    yield
    events._pending_msgs.clear()
    events._activity_event = None


def _fake_event(chat_id, message_id, name="Alice", username="alice"):
    # A real User, so utils.get_display_name() resolves the way it does in production.
    sender = User(id=abs(chat_id), first_name=name, username=username, bot=False, is_self=False)

    async def _get_sender():
        return sender

    return SimpleNamespace(
        is_private=True,
        chat_id=chat_id,
        message=SimpleNamespace(id=message_id),
        get_sender=_get_sender,
    )


@pytest.mark.asyncio
async def test_same_chat_id_on_two_accounts_stays_separate():
    """Distinct accounts can legitimately share a chat_id; they must not merge."""
    await events._on_new_incoming(_fake_event(555, 1), "work")
    await events._on_new_incoming(_fake_event(555, 2), "personal")

    assert len(events._pending_msgs) == 2
    assert {record["account"] for record in events._pending_msgs.values()} == {
        "work",
        "personal",
    }
    assert all(record["count"] == 1 for record in events._pending_msgs.values())


@pytest.mark.asyncio
async def test_repeat_messages_on_one_account_still_group_into_one_burst():
    await events._on_new_incoming(_fake_event(555, 1), "work")
    await events._on_new_incoming(_fake_event(555, 2), "work")

    assert len(events._pending_msgs) == 1
    record = next(iter(events._pending_msgs.values()))
    assert record["count"] == 2
    assert record["first_id"] == 1
    assert record["last_id"] == 2


@pytest.mark.asyncio
async def test_wait_for_new_message_reports_the_receiving_account():
    await events._on_new_incoming(_fake_event(555, 1), "work")

    payload = json.loads(await events.wait_for_new_message(timeout=0.01))

    assert payload["event"] is True
    assert payload["pending_chats"] == [
        {
            "account": "work",
            "chat_id": 555,
            "name": "Alice",
            "username": "alice",
            "count": 1,
            "last_message_id": 1,
        }
    ]


@pytest.mark.asyncio
async def test_wait_for_settled_message_reports_the_receiving_account():
    await events._on_new_incoming(_fake_event(777, 9), "personal")

    payload = json.loads(await events.wait_for_settled_message(settle_ms=0, max_wait_ms=50))

    assert payload["event"] is True
    assert payload["account"] == "personal"
    assert payload["chat_id"] == 777
    assert payload["last_message_id"] == 9


@pytest.mark.asyncio
async def test_settled_messages_drain_per_account_not_per_chat_id():
    await events._on_new_incoming(_fake_event(555, 1), "work")
    await events._on_new_incoming(_fake_event(555, 2), "personal")

    first = json.loads(await events.wait_for_settled_message(settle_ms=0, max_wait_ms=50))
    second = json.loads(await events.wait_for_settled_message(settle_ms=0, max_wait_ms=50))

    assert {first["account"], second["account"]} == {"work", "personal"}
    assert first["chat_id"] == second["chat_id"] == 555
    assert events._pending_msgs == {}


@pytest.fixture
def two_accounts(monkeypatch):
    """Make 'work' and 'personal' resolvable as configured account labels."""
    monkeypatch.setattr(events, "clients", {"work": object(), "personal": object()})


@pytest.mark.asyncio
async def test_wait_for_new_message_filters_to_one_account(two_accounts):
    await events._on_new_incoming(_fake_event(555, 1), "work")
    await events._on_new_incoming(_fake_event(666, 2), "personal")

    payload = json.loads(await events.wait_for_new_message(timeout=0.05, account="work"))

    assert [chat["chat_id"] for chat in payload["pending_chats"]] == [555]
    assert payload["pending_chats"][0]["account"] == "work"


@pytest.mark.asyncio
async def test_wait_for_new_message_ignores_traffic_on_other_accounts(two_accounts):
    """A message on another account must not wake a filtered waiter."""
    await events._on_new_incoming(_fake_event(555, 1), "work")

    payload = json.loads(await events.wait_for_new_message(timeout=0.05, account="personal"))

    assert payload["event"] is False
    assert payload["reason"] == "timeout"


@pytest.mark.asyncio
async def test_wait_for_settled_message_only_drains_the_named_account(two_accounts):
    await events._on_new_incoming(_fake_event(555, 1), "work")
    await events._on_new_incoming(_fake_event(555, 2), "personal")

    payload = json.loads(
        await events.wait_for_settled_message(settle_ms=0, max_wait_ms=50, account="personal")
    )

    assert payload["account"] == "personal"
    assert list(events._pending_msgs) == [("work", 555)]


@pytest.mark.asyncio
async def test_wait_for_settled_message_ignores_traffic_on_other_accounts(two_accounts):
    await events._on_new_incoming(_fake_event(555, 1), "work")

    payload = json.loads(
        await events.wait_for_settled_message(settle_ms=0, max_wait_ms=50, account="personal")
    )

    assert payload["event"] is False
    assert payload["reason"] == "timeout"
    assert list(events._pending_msgs) == [("work", 555)]


@pytest.mark.asyncio
async def test_chat_and_account_filters_compose(two_accounts):
    """Same chat_id on both accounts: naming one account must pick exactly one."""
    await events._on_new_incoming(_fake_event(555, 1), "work")
    await events._on_new_incoming(_fake_event(555, 2), "personal")

    payload = json.loads(
        await events.wait_for_settled_message(
            settle_ms=0, max_wait_ms=50, chat_id=555, account="personal"
        )
    )

    assert payload["account"] == "personal"
    assert payload["chat_id"] == 555
    assert list(events._pending_msgs) == [("work", 555)]


@pytest.mark.asyncio
async def test_account_filter_is_case_insensitive(two_accounts):
    await events._on_new_incoming(_fake_event(555, 1), "work")

    payload = json.loads(await events.wait_for_new_message(timeout=0.05, account="WORK"))

    assert payload["pending_chats"][0]["account"] == "work"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_call",
    [
        lambda: events.wait_for_new_message(timeout=0.05, account="nope"),
        lambda: events.wait_for_settled_message(settle_ms=0, max_wait_ms=50, account="nope"),
    ],
)
async def test_unknown_account_reports_the_configured_labels(two_accounts, tool_call):
    result = await tool_call()

    assert "nope" in result
    assert "work" in result and "personal" in result


def _register_fake_clients(monkeypatch):
    """Register handlers against two fake clients, returning label -> callback."""
    registered = {}

    class _FakeClient:
        def __init__(self, label):
            self.label = label

        def add_event_handler(self, callback, _event):
            registered[self.label] = callback

    monkeypatch.setattr(
        events,
        "clients",
        {"work": _FakeClient("work"), "personal": _FakeClient("personal")},
    )
    events.register_incoming_handlers()
    return registered


def test_register_incoming_handlers_binds_each_account_label(monkeypatch):
    assert set(_register_fake_clients(monkeypatch)) == {"work", "personal"}


@pytest.mark.asyncio
async def test_registered_handler_tags_events_with_its_own_account(monkeypatch):
    registered = _register_fake_clients(monkeypatch)

    await registered["personal"](_fake_event(321, 5))

    record = next(iter(events._pending_msgs.values()))
    assert record["account"] == "personal"
