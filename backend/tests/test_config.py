from __future__ import annotations

from config import Settings


def test_settings_accepts_release_style_debug_values():
    settings = Settings(DEBUG="release", ALLOW_REMOTE_ACCESS="prod", LOG_JSON="debug")

    assert settings.DEBUG is False
    assert settings.ALLOW_REMOTE_ACCESS is False
    assert settings.LOG_JSON is True
