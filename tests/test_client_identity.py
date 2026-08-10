from telegram_mcp.client_identity import client_identity_kwargs


_BASE_KEYS = ("TELEGRAM_DEVICE_MODEL", "TELEGRAM_SYSTEM_VERSION", "TELEGRAM_APP_VERSION")


def _clear_device_env(monkeypatch):
    for key in _BASE_KEYS:
        monkeypatch.delenv(key, raising=False)
        for label in ("WORK", "PERSONAL"):
            monkeypatch.delenv(f"{key}_{label}", raising=False)


def test_client_identity_kwargs_empty_when_unset(monkeypatch):
    _clear_device_env(monkeypatch)

    assert client_identity_kwargs() == {}


def test_client_identity_kwargs_maps_all_variables(monkeypatch):
    _clear_device_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL", "Telegram MCP")
    monkeypatch.setenv("TELEGRAM_SYSTEM_VERSION", "2.0")
    monkeypatch.setenv("TELEGRAM_APP_VERSION", "3.1")

    assert client_identity_kwargs() == {
        "device_model": "Telegram MCP",
        "system_version": "2.0",
        "app_version": "3.1",
    }


def test_client_identity_kwargs_ignores_empty_values(monkeypatch):
    _clear_device_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL", "Telegram MCP")
    monkeypatch.setenv("TELEGRAM_SYSTEM_VERSION", "")

    assert client_identity_kwargs() == {"device_model": "Telegram MCP"}


def test_suffixed_variables_override_the_global_default(monkeypatch):
    _clear_device_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL", "shared")
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL_WORK", "work laptop")

    assert client_identity_kwargs("work") == {"device_model": "work laptop"}
    assert client_identity_kwargs("personal") == {"device_model": "shared"}


def test_label_is_uppercased_to_match_the_environment(monkeypatch):
    """Account labels are lowercased at discovery; env var names are upper."""
    _clear_device_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL_WORK", "work laptop")

    assert client_identity_kwargs("WoRk") == {"device_model": "work laptop"}


def test_per_label_and_global_values_mix_per_field(monkeypatch):
    _clear_device_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL_WORK", "work laptop")
    monkeypatch.setenv("TELEGRAM_SYSTEM_VERSION", "linux")
    monkeypatch.setenv("TELEGRAM_APP_VERSION", "2.0.1")

    assert client_identity_kwargs("work") == {
        "device_model": "work laptop",
        "system_version": "linux",
        "app_version": "2.0.1",
    }


def test_empty_suffixed_value_falls_back_to_the_global(monkeypatch):
    """Matches _get_proxy_env: an empty override is treated as unset."""
    _clear_device_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL", "shared")
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL_WORK", "")

    assert client_identity_kwargs("work") == {"device_model": "shared"}


def test_no_label_ignores_suffixed_variables(monkeypatch):
    """The session generator calls this without a label; it must not leak one."""
    _clear_device_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_DEVICE_MODEL_WORK", "work laptop")

    assert client_identity_kwargs() == {}
