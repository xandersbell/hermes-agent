import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gateway.config import Platform, PlatformConfig, load_gateway_config


def _make_adapter(
    require_mention=None,
    free_response_chats=None,
    mention_patterns=None,
    allow_from=None,
    group_allow_from=None,
):
    from gateway.platforms.telegram import TelegramAdapter

    extra = {}
    if require_mention is not None:
        extra["require_mention"] = require_mention
    if free_response_chats is not None:
        extra["free_response_chats"] = free_response_chats
    if mention_patterns is not None:
        extra["mention_patterns"] = mention_patterns
    if allow_from is not None:
        extra["allow_from"] = allow_from
    if group_allow_from is not None:
        extra["group_allow_from"] = group_allow_from

    adapter = object.__new__(TelegramAdapter)
    adapter.platform = Platform.TELEGRAM
    adapter.config = PlatformConfig(enabled=True, token="***", extra=extra)
    adapter._bot = SimpleNamespace(id=999, username="hermes_bot")
    adapter._message_handler = AsyncMock()
    adapter._pending_text_batches = {}
    adapter._pending_text_batch_tasks = {}
    adapter._text_batch_delay_seconds = 0.01
    adapter._mention_patterns = adapter._compile_mention_patterns()
    adapter._allow_from = TelegramAdapter._coerce_list(extra.get("allow_from"))
    adapter._group_allow_from = TelegramAdapter._coerce_list(
        extra.get("group_allow_from")
    )
    return adapter


def _group_message(
    text="hello",
    *,
    chat_id=-100,
    from_user_id=111,
    reply_to_bot=False,
    entities=None,
    caption=None,
    caption_entities=None,
):
    reply_to_message = None
    if reply_to_bot:
        reply_to_message = SimpleNamespace(from_user=SimpleNamespace(id=999))
    return SimpleNamespace(
        text=text,
        caption=caption,
        entities=entities or [],
        caption_entities=caption_entities or [],
        chat=SimpleNamespace(id=chat_id, type="group"),
        from_user=SimpleNamespace(id=from_user_id),
        reply_to_message=reply_to_message,
    )


def _dm_message(text="hello", *, from_user_id=111):
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=from_user_id, type="private"),
        from_user=SimpleNamespace(id=from_user_id),
    )


def _mention_entity(text, mention="@hermes_bot"):
    offset = text.index(mention)
    return SimpleNamespace(type="mention", offset=offset, length=len(mention))


def test_group_messages_can_be_opened_via_config():
    adapter = _make_adapter(require_mention=False)

    assert adapter._should_process_message(_group_message("hello everyone")) is True


def test_group_messages_can_require_direct_trigger_via_config():
    adapter = _make_adapter(require_mention=True)

    assert adapter._should_process_message(_group_message("hello everyone")) is False
    assert (
        adapter._should_process_message(
            _group_message(
                "hi @hermes_bot", entities=[_mention_entity("hi @hermes_bot")]
            )
        )
        is True
    )
    assert (
        adapter._should_process_message(_group_message("replying", reply_to_bot=True))
        is True
    )
    assert (
        adapter._should_process_message(_group_message("/status"), is_command=True)
        is True
    )


def test_free_response_chats_bypass_mention_requirement():
    adapter = _make_adapter(require_mention=True, free_response_chats=["-200"])

    assert (
        adapter._should_process_message(_group_message("hello everyone", chat_id=-200))
        is True
    )
    assert (
        adapter._should_process_message(_group_message("hello everyone", chat_id=-201))
        is False
    )


def test_regex_mention_patterns_allow_custom_wake_words():
    adapter = _make_adapter(require_mention=True, mention_patterns=[r"^\s*chompy\b"])

    assert adapter._should_process_message(_group_message("chompy status")) is True
    assert adapter._should_process_message(_group_message("   chompy help")) is True
    assert adapter._should_process_message(_group_message("hey chompy")) is False


def test_invalid_regex_patterns_are_ignored():
    adapter = _make_adapter(
        require_mention=True, mention_patterns=[r"(", r"^\s*chompy\b"]
    )

    assert adapter._should_process_message(_group_message("chompy status")) is True
    assert adapter._should_process_message(_group_message("hello everyone")) is False


def test_config_bridges_telegram_group_settings(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        "telegram:\n"
        "  require_mention: true\n"
        "  mention_patterns:\n"
        '    - "^\\\\s*chompy\\\\b"\n'
        "  free_response_chats:\n"
        '    - "-123"\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("TELEGRAM_REQUIRE_MENTION", raising=False)
    monkeypatch.delenv("TELEGRAM_MENTION_PATTERNS", raising=False)
    monkeypatch.delenv("TELEGRAM_FREE_RESPONSE_CHATS", raising=False)

    config = load_gateway_config()

    assert config is not None
    assert __import__("os").environ["TELEGRAM_REQUIRE_MENTION"] == "true"
    assert json.loads(__import__("os").environ["TELEGRAM_MENTION_PATTERNS"]) == [
        r"^\s*chompy\b"
    ]
    assert __import__("os").environ["TELEGRAM_FREE_RESPONSE_CHATS"] == "-123"


def test_config_bridges_telegram_allowlist(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    yaml_content = 'telegram:\n  allow_from: "111,222"\n  group_allow_from: "333"\n'
    (hermes_home / "config.yaml").write_text(yaml_content, encoding="utf-8")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("TELEGRAM_GROUP_ALLOWED_USERS", raising=False)

    config = load_gateway_config()

    assert config is not None
    assert __import__("os").environ["TELEGRAM_ALLOWED_USERS"] == "111,222"
    assert __import__("os").environ["TELEGRAM_GROUP_ALLOWED_USERS"] == "333"


# User allowlist tests


def test_group_allow_from_accepts_whitelisted_user():
    adapter = _make_adapter(group_allow_from=["111", "222"])
    assert (
        adapter._should_process_message(_group_message("hello", from_user_id=111))
        is True
    )
    assert (
        adapter._should_process_message(_group_message("hello", from_user_id=222))
        is True
    )


def test_group_allow_from_rejects_non_whitelisted_user():
    adapter = _make_adapter(group_allow_from=["111", "222"])
    assert (
        adapter._should_process_message(_group_message("hello", from_user_id=333))
        is False
    )


def test_group_allow_from_wildcard_accepts_all():
    adapter = _make_adapter(group_allow_from=["*"])
    assert (
        adapter._should_process_message(_group_message("hello", from_user_id=333))
        is True
    )


def test_dm_allow_from_accepts_whitelisted_user():
    adapter = _make_adapter(allow_from=["111", "222"])
    assert (
        adapter._should_process_message(_dm_message("hello", from_user_id=111)) is True
    )
    assert (
        adapter._should_process_message(_dm_message("hello", from_user_id=222)) is True
    )


def test_dm_allow_from_rejects_non_whitelisted_user():
    adapter = _make_adapter(allow_from=["111", "222"])
    assert (
        adapter._should_process_message(_dm_message("hello", from_user_id=333)) is False
    )
