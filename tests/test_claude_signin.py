"""Signing in to Claude: a key, or federation inside a GitHub job (no key stored). Nothing here reaches GitHub or
Anthropic: the token request is a stub."""

from __future__ import annotations

import io
import json

import anthropic
import pytest

from collectors.core import claude

ALL = ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", *claude.FEDERATION, *claude.GITHUB)
FEDERATED = {"ANTHROPIC_FEDERATION_RULE_ID": "fdrl_1", "ANTHROPIC_SERVICE_ACCOUNT_ID": "svac_1",
             "ANTHROPIC_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000000",
             "ACTIONS_ID_TOKEN_REQUEST_URL": "https://runner.example/token?api-version=2.0",
             "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runner-secret"}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in ALL:
        monkeypatch.delenv(name, raising=False)


def federate(monkeypatch, skip: str = ""):
    for name, value in FEDERATED.items():
        if name != skip:
            monkeypatch.setenv(name, value)


def test_nothing_is_not_set_up():
    assert not claude.configured()


def test_a_key_is_enough(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert claude.configured()


def test_an_empty_key_is_not(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert not claude.configured()


def test_federation_with_every_variable(monkeypatch):
    federate(monkeypatch)
    assert claude.configured()


@pytest.mark.parametrize("missing", sorted(FEDERATED))
def test_federation_missing_one_is_not(monkeypatch, missing):
    # A job without "id-token: write" has no ACTIONS_ID_TOKEN_REQUEST_*: not set up, rather than failing every case.
    federate(monkeypatch, skip=missing)
    assert not claude.configured()


def test_the_github_token_is_asked_for_anthropic(monkeypatch):
    federate(monkeypatch)
    asked = []

    def urlopen(request, timeout):
        asked.append((request.full_url, request.get_header("Authorization")))
        return io.BytesIO(json.dumps({"value": "jwt-1"}).encode())

    monkeypatch.setattr(claude.urllib.request, "urlopen", urlopen)
    assert claude.github_token() == "jwt-1"
    assert asked == [("https://runner.example/token?api-version=2.0&audience=https://api.anthropic.com",
                      "Bearer runner-secret")]


def test_github_refusing_is_a_sign_in_error(monkeypatch):
    federate(monkeypatch)

    def urlopen(request, timeout):
        raise OSError("refused")

    monkeypatch.setattr(claude.urllib.request, "urlopen", urlopen)
    with pytest.raises(anthropic.WorkloadIdentityError):
        claude.github_token()


def test_an_empty_github_answer_is_a_sign_in_error(monkeypatch):
    federate(monkeypatch)
    monkeypatch.setattr(claude.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(b'{"value": ""}'))
    with pytest.raises(anthropic.WorkloadIdentityError):
        claude.github_token()


def test_federation_signs_in_without_a_key(monkeypatch):
    federate(monkeypatch)
    made = {}
    real = anthropic.WorkloadIdentityCredentials

    def spy(**kwargs):
        made.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(anthropic, "WorkloadIdentityCredentials", spy)
    claude.client()
    assert made["identity_token_provider"] is claude.github_token
    assert (made["federation_rule_id"], made["service_account_id"]) == ("fdrl_1", "svac_1")
    assert made["workspace_id"] is None


def test_a_key_by_hand_wins(monkeypatch):
    federate(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(anthropic, "WorkloadIdentityCredentials", lambda **kw: pytest.fail("federation used"))
    claude.client()
