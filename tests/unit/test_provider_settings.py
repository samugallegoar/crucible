"""API keys and provider selection: environment, ``.env``, masking (ADR-0063)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.providers.errors import MissingApiKeyError
from crucible.data.providers.settings import ApiKey, ProviderSettings, parse_dotenv

SECRET = "tk_live_0123456789abcdef"


def test_the_test_suite_refuses_real_network_connections() -> None:
    with socket.socket() as sock, pytest.raises(RuntimeError, match="network"):
        sock.connect(("93.184.216.34", 80))  # a public address: must never be reached


def test_parse_dotenv_reads_keys_comments_quotes_and_export(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n"
        "\n"
        "TIINGO_API_KEY=abc123\n"
        "export OTHER='quoted value'\n"
        'DOUBLE="with # hash"\n'
        "TRAILING=value # inline comment\n"
        "EMPTY=\n",
        encoding="utf-8",
    )
    assert parse_dotenv(path) == {
        "TIINGO_API_KEY": "abc123",
        "OTHER": "quoted value",
        "DOUBLE": "with # hash",
        "TRAILING": "value",
        "EMPTY": "",
    }


def test_parse_dotenv_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert parse_dotenv(tmp_path / "nope.env") == {}


def test_a_malformed_line_is_refused_without_echoing_its_content(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(f"GOOD=1\nthis line has {SECRET} but no equals sign\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match=r"line 2") as excinfo:
        parse_dotenv(path)
    assert SECRET not in str(excinfo.value)


def test_the_real_environment_wins_over_the_dotenv_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("TIINGO_API_KEY=from_file\nCRUCIBLE_DATA_PROVIDER=tiingo\n", encoding="utf-8")
    settings = ProviderSettings.load(environ={"TIINGO_API_KEY": "from_env"}, dotenv_path=path)
    key = settings.api_key("TIINGO_API_KEY", provider="tiingo")
    assert key.reveal() == "from_env"
    assert settings.default_provider() == "tiingo"  # only in the file, so the file supplies it


def test_default_provider_is_yfinance_without_any_setup(tmp_path: Path) -> None:
    settings = ProviderSettings.load(environ={}, dotenv_path=tmp_path / ".env")
    assert settings.default_provider() == "yfinance"


def test_a_missing_key_explains_how_to_get_and_set_one(tmp_path: Path) -> None:
    settings = ProviderSettings.load(environ={}, dotenv_path=tmp_path / ".env")
    with pytest.raises(MissingApiKeyError) as excinfo:
        settings.api_key("TIINGO_API_KEY", provider="tiingo")
    message = str(excinfo.value)
    assert "TIINGO_API_KEY" in message
    assert "tiingo.com" in message
    assert ".env" in message
    assert ".env.example" in message
    assert isinstance(excinfo.value, ConfigurationError)


def test_a_blank_key_counts_as_missing(tmp_path: Path) -> None:
    settings = ProviderSettings.load(environ={"TIINGO_API_KEY": "   "}, dotenv_path=tmp_path / "x")
    with pytest.raises(MissingApiKeyError):
        settings.api_key("TIINGO_API_KEY", provider="tiingo")


def test_an_api_key_never_shows_its_value() -> None:
    key = ApiKey(SECRET)
    for rendering in (repr(key), str(key), f"{key}", f"{key!r}", repr([key]), repr({"k": key})):
        assert SECRET not in rendering
    assert key.reveal() == SECRET


def test_settings_do_not_leak_a_key_in_their_repr(tmp_path: Path) -> None:
    settings = ProviderSettings.load(environ={"TIINGO_API_KEY": SECRET}, dotenv_path=tmp_path / "x")
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)


def test_loading_settings_does_not_modify_the_process_environment(tmp_path: Path) -> None:
    import os

    path = tmp_path / ".env"
    path.write_text("SOME_UNIQUE_CRUCIBLE_TEST_VAR=1\n", encoding="utf-8")
    ProviderSettings.load(environ={}, dotenv_path=path)
    assert "SOME_UNIQUE_CRUCIBLE_TEST_VAR" not in os.environ


def test_a_comment_after_a_quoted_value_is_not_part_of_the_value(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text('TIINGO_API_KEY="abc" # my key\n' + "OTHER='x y'  # note\n", encoding="utf-8")
    assert parse_dotenv(path) == {"TIINGO_API_KEY": "abc", "OTHER": "x y"}


def test_settings_cannot_be_pickled_or_compared_by_their_secrets(tmp_path: Path) -> None:
    import pickle

    one = ProviderSettings.load(environ={"TIINGO_API_KEY": "aaa"}, dotenv_path=tmp_path / "x")
    two = ProviderSettings.load(environ={"TIINGO_API_KEY": "bbb"}, dotenv_path=tmp_path / "x")
    with pytest.raises(TypeError, match="pickled"):
        pickle.dumps(one)
    assert one == two  # equality must not be an oracle for the secret values
