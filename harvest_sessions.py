#!/usr/bin/env python3
"""Harvest Telethon session strings from Telegram Desktop tdata folders.

Reads the accounts already logged into the tg-accounts/instance-* windows and
authorises a SEPARATE session for each, then writes the results straight into
.env. Saves logging every account in a second time.

Run with:

    uv run --with opentele2 python harvest_sessions.py

Why a separate session rather than reusing the desktop one: opentele2 can
convert with UseCurrentSession, which copies the *same* auth key. Telegram
raises AUTH_KEY_DUPLICATED when one auth key sends requests from two
connections at once, so the server and the desktop window would fight.
CreateNewSession uses the existing login to authorise a brand-new session, so
both run side by side -- which is the whole point of watching the automation
happen in the GUI.

Session strings are written directly to .env and never printed, so they do not
end up in terminal scrollback or logs.

Each label is pinned to the account's numeric user id, recorded in .env as a
comment above the session string. Positions inside tdata are NOT stable --
logging an account out, or adding one, renumbers the rest and can move
accounts between instances -- so a purely positional mapping would silently
repoint a label at a different person on the next run. On re-run the pin is
checked and a changed identity is reported instead of being written.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import dotenv_values

REPO = Path(__file__).resolve().parent
ENV_PATH = REPO / ".env"

# label -> (instance number, index of the account within that instance)
LAYOUT = [
    ("ACC1", 1, 0),
    ("ACC2", 1, 1),
    ("ACC3", 1, 2),
    ("ACC4", 2, 0),
    ("ACC5", 2, 1),
    ("ACC6", 2, 2),
]


def _require_credentials() -> tuple[int, str]:
    env = dotenv_values(ENV_PATH)
    api_id, api_hash = env.get("TELEGRAM_API_ID"), env.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash or "REPLACE_ME" in (api_id, api_hash):
        raise SystemExit(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.\n"
            "Get them from https://my.telegram.org/apps -- Telegram requires each\n"
            "application to use its own api_id."
        )
    try:
        return int(api_id), api_hash
    except ValueError:
        raise SystemExit(f"TELEGRAM_API_ID must be an integer, got {api_id!r}.") from None


def _write_env_value(text: str, key: str, value: str, pin: str) -> str:
    """Replace `KEY=...` in .env, carrying an identity comment above it."""
    pattern = re.compile(rf"^(?:# {re.escape(key)} -> .*\n)?{re.escape(key)}=.*$", re.MULTILINE)
    if not pattern.search(text):
        raise SystemExit(f"{key} not found in .env -- refusing to guess where to add it.")
    return pattern.sub(f"# {key} -> {pin}\n{key}={value}", text)


def _existing_pin(text: str, key: str) -> str | None:
    """The user id this label was pinned to on a previous run, if any."""
    found = re.search(rf"^# {re.escape(key)} -> id=(\d+)", text, re.MULTILINE)
    return found.group(1) if found else None


async def main() -> None:
    from opentele2.api import API, CreateNewSession
    from opentele2.td import TDesktop

    api_id, api_hash = _require_credentials()

    desktops = {}
    for instance in (1, 2):
        folder = REPO / "tg-accounts" / f"instance-{instance}" / "tdata"
        desktop = TDesktop(str(folder))
        if not desktop.isLoaded():
            raise SystemExit(f"No accounts loaded from {folder}")
        desktops[instance] = desktop
        print(f"instance-{instance}: {len(desktop.accounts)} account(s)", file=sys.stderr)

    env_text = ENV_PATH.read_text(encoding="utf-8")
    harvested = 0
    conflicts = []

    for label, instance, index in LAYOUT:
        accounts = desktops[instance].accounts
        if index >= len(accounts):
            print(f"  {label}: no account at index {index}, skipping", file=sys.stderr)
            continue

        account = accounts[index]

        # Positions shift when accounts are added or removed. Refuse to
        # overwrite a label that was pinned to a different account, rather
        # than silently repointing it -- with draft-first that would put
        # drafts in the wrong person's chats.
        pinned = _existing_pin(env_text, f"TELEGRAM_SESSION_STRING_{label}")
        if pinned is not None and pinned != str(account.UserId):
            conflicts.append((label, pinned, account.UserId))
            print(
                f"  {label}: SKIPPED -- pinned to id={pinned}, "
                f"instance-{instance}[{index}] now holds id={account.UserId}",
                file=sys.stderr,
            )
            continue
        # Use the caller's own api_id, as Telegram's terms require. Not the
        # bundled official-app credentials: those exist to make automation
        # indistinguishable from the official client, which is circumvention,
        # and a session authorised under one api_id should be used with it.
        api = API.TelegramDesktop.Generate(system="linux")
        api.api_id, api.api_hash = api_id, api_hash

        client = await account.ToTelethon(session=None, flag=CreateNewSession, api=api)
        await client.connect()
        me = await client.get_me()
        session_string = client.session.save()
        await client.disconnect()

        pin = f"id={me.id} @{me.username or '-'} ({me.first_name}) [instance-{instance}]"
        env_text = _write_env_value(
            env_text, f"TELEGRAM_SESSION_STRING_{label}", session_string, pin
        )
        harvested += 1
        # Identify the account, never the secret.
        print(f"  {label}: {pin}", file=sys.stderr)

    ENV_PATH.write_text(env_text, encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)
    print(f"\nWrote {harvested} session string(s) to {ENV_PATH} (chmod 600).", file=sys.stderr)

    if conflicts:
        print(
            f"\n{len(conflicts)} label(s) left untouched because the account behind that\n"
            "position changed. Either restore the account to that slot, or clear the\n"
            "`# TELEGRAM_SESSION_STRING_<LABEL> -> id=...` comment to re-pin it:",
            file=sys.stderr,
        )
        for label, was, now in conflicts:
            print(f"  {label}: was id={was}, position now holds id={now}", file=sys.stderr)

    print(
        "\nEach harvested account now shows a second entry under Settings > Devices.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
