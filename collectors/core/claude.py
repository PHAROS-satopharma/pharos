"""The Claude client, and whether this run can sign in to Claude at all.

Two ways in:

* **Federation (the GitHub workflows).** No Claude key is stored anywhere. Each time the SDK needs an access token
  it asks GitHub for a fresh OIDC token for this job (audience ``https://api.anthropic.com``) and trades it at
  Anthropic for a short-lived token of the service account ``pharos``. Anthropic's federation rule accepts only
  this repository on ``main``. GitHub's tokens live about 5 minutes and are single-use, so the token is fetched
  again on every exchange, never kept in a file. The job needs ``permissions: id-token: write`` and the three
  repository variables below (identifiers, not secrets).
* **A key (a person running a collector by hand):** ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

FEDERATION = ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_SERVICE_ACCOUNT_ID")
GITHUB = ("ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN")
AUDIENCE = "https://api.anthropic.com"

MISSING = "the reader is not set up (no Claude sign-in: neither federation nor ANTHROPIC_API_KEY)"


def _federated() -> bool:
    return all(os.environ.get(name) for name in (*FEDERATION, *GITHUB))


def configured() -> bool:
    """True when this run has a way in: a key, or federation inside a GitHub job allowed to ask for its token."""
    return bool(os.environ.get("ANTHROPIC_API_KEY")) or _federated()


def github_token() -> str:
    """A fresh GitHub OIDC token for this job, for Anthropic. Raises WorkloadIdentityError so callers see one error."""
    import anthropic

    url = f"{os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']}&audience={AUDIENCE}"
    bearer = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - GitHub's own runner URL
            value = json.load(response).get("value")
    except Exception as exc:  # noqa: BLE001 - any failure here is "GitHub would not give the token"
        raise anthropic.WorkloadIdentityError(
            f"GitHub did not give this job its sign-in token ({type(exc).__name__})") from None
    if not value:
        raise anthropic.WorkloadIdentityError("GitHub gave this job an empty sign-in token")
    return value


def client() -> Any:
    """The Claude client: the key when one is set (by hand), else federation."""
    import anthropic

    if os.environ.get("ANTHROPIC_API_KEY") or not _federated():
        return anthropic.Anthropic()
    return anthropic.Anthropic(credentials=anthropic.WorkloadIdentityCredentials(
        identity_token_provider=github_token,
        federation_rule_id=os.environ["ANTHROPIC_FEDERATION_RULE_ID"],
        organization_id=os.environ["ANTHROPIC_ORGANIZATION_ID"],
        service_account_id=os.environ["ANTHROPIC_SERVICE_ACCOUNT_ID"],
        workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID") or None,
    ))


def check() -> str:
    """One harmless call (the model list) that proves this run can sign in; says which way it signed in."""
    way = "key" if os.environ.get("ANTHROPIC_API_KEY") else "federation"
    if not configured():
        raise SystemExit(MISSING)
    model = next(iter(client().models.list(limit=1)), None)
    return f"Claude sign-in works ({way}): {getattr(model, 'id', 'no model listed')}"


if __name__ == "__main__":
    print(check())
