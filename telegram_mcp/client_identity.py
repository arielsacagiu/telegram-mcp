"""Resolve the Telethon device identity used when connecting to Telegram.

These values are what Telegram shows in Settings > Devices (active sessions).
When they are not provided, Telethon falls back to the host platform (for
example ``arm64``), and because the values are re-sent on every connection,
a long-running server would otherwise overwrite the name chosen during login
on each reconnect. Making them configurable keeps a stable, recognisable name.

Each variable also accepts an ``_<LABEL>`` suffix so every configured account
can be told apart in that list; without it they all report the same device,
which is the list you check to spot a session you did not expect.
"""

import os
from typing import Optional

# Maps the Telethon constructor keyword to the environment variable that sets it.
_DEVICE_ENV = {
    "device_model": "TELEGRAM_DEVICE_MODEL",
    "system_version": "TELEGRAM_SYSTEM_VERSION",
    "app_version": "TELEGRAM_APP_VERSION",
}


def _device_env(env_var: str, label: Optional[str]) -> Optional[str]:
    """Resolve a device variable with an optional ``_<LABEL>`` suffix.

    Per-account values override the unsuffixed defaults, so a house default can
    coexist with per-label overrides. Mirrors ``_get_proxy_env`` in runtime.py,
    including treating an empty override as unset.
    """
    if label:
        suffixed = os.environ.get(f"{env_var}_{label.upper()}")
        if suffixed:
            return suffixed
    return os.environ.get(env_var)


def client_identity_kwargs(label: Optional[str] = None) -> dict:
    """Return TelegramClient device kwargs derived from the environment.

    Only variables that are set to a non-empty value are included, so unset
    ones keep Telethon's own defaults.

    With ``label``, ``TELEGRAM_<NAME>_<LABEL>`` wins over the unsuffixed
    variable, so each account can be told apart in Telegram's active-sessions
    list instead of all of them sharing one device name. Without a label, only
    the unsuffixed variables are read.
    """
    kwargs = {}
    for kwarg, env_var in _DEVICE_ENV.items():
        value = _device_env(env_var, label)
        if value:
            kwargs[kwarg] = value
    return kwargs
