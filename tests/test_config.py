import pytest
from pydantic import ValidationError

from switchgear.config import Settings


def test_defaults_and_tier_map(monkeypatch):
    monkeypatch.setenv("SWITCHGEAR_OWNER_EMAIL", "me@example.com")
    monkeypatch.setenv("SWITCHGEAR_MODEL_BULK", "cheap/model")
    s = Settings(_env_file=None)
    assert s.owner_email == "me@example.com"
    assert s.model_for("bulk") == "cheap/model"
    assert s.model_for("chat") == s.model_chat
    assert s.run_token_budget == 200000


def test_unknown_tier_raises():
    s = Settings(_env_file=None, owner_email="me@example.com")
    try:
        s.model_for("nope")
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


def test_scheduler_backend_is_a_validated_enum():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, scheduler_backend="gcp")


def test_validate_runtime_allows_unclaimed_boot():
    s = Settings(_env_file=None)  # no password hash, no owner email
    s.validate_runtime()  # must not raise


def test_setup_token_reads_env(monkeypatch):
    monkeypatch.setenv("SWITCHGEAR_SETUP_TOKEN", "preset-token")
    assert Settings(_env_file=None).setup_token == "preset-token"
