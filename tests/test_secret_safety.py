from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.redaction import redact
from tests.conftest import make_api_key_headers


def test_secret_names_must_be_glyphhold_env_vars(secrets_client: TestClient) -> None:
    headers = make_api_key_headers(scopes=["secrets:write"], actor="secret-writer")

    invalid_response = secrets_client.post(
        "/api/v1/secrets",
        headers=headers,
        json={"name": "SERVICE_API_KEY", "value": "hidden"},
    )
    assert invalid_response.status_code == 400
    assert "GLYPHHOLD_*" in invalid_response.json()["detail"]
    assert "hidden" not in invalid_response.text

    valid_response = secrets_client.post(
        "/api/v1/secrets",
        headers=headers,
        json={"name": "GLYPHHOLD_SERVICE_API_KEY", "value": "hidden"},
    )
    assert valid_response.status_code == 201
    assert valid_response.json()["name"] == "GLYPHHOLD_SERVICE_API_KEY"
    assert "hidden" not in valid_response.text


def test_secret_allowed_agent_and_tool_are_enforced(secrets_client: TestClient) -> None:
    headers = make_api_key_headers(
        scopes=["secrets:write", "secrets:reveal", "events:read"],
        actor="secret-agent",
    )
    create_response = secrets_client.post(
        "/api/v1/secrets",
        headers=headers,
        json={
            "name": "GLYPHHOLD_RESTRICTED_TOKEN",
            "value": "restricted-secret-value",
            "allowed_agents": ["agent-a"],
            "allowed_tools": ["tool-a"],
        },
    )
    assert create_response.status_code == 201

    denied_agent_response = secrets_client.post(
        "/api/v1/secrets/GLYPHHOLD_RESTRICTED_TOKEN/reveal",
        headers=headers,
        json={"requesting_agent": "agent-b", "tool": "tool-a", "purpose": "test"},
    )
    assert denied_agent_response.status_code == 403
    assert "restricted-secret-value" not in denied_agent_response.text

    denied_tool_response = secrets_client.post(
        "/api/v1/secrets/GLYPHHOLD_RESTRICTED_TOKEN/reveal",
        headers=headers,
        json={"requesting_agent": "agent-a", "tool": "tool-b", "purpose": "test"},
    )
    assert denied_tool_response.status_code == 403
    assert "restricted-secret-value" not in denied_tool_response.text

    allowed_response = secrets_client.post(
        "/api/v1/secrets/GLYPHHOLD_RESTRICTED_TOKEN/reveal",
        headers=headers,
        json={"requesting_agent": "agent-a", "tool": "tool-a", "purpose": "test"},
    )
    assert allowed_response.status_code == 200
    assert allowed_response.json()["value"] == "restricted-secret-value"

    events_response = secrets_client.get("/api/v1/events", headers=headers)
    assert events_response.status_code == 200
    assert "restricted-secret-value" not in events_response.text


def test_redaction_keeps_safe_secret_status_fields() -> None:
    redacted = redact(
        {
            "secrets_enabled": True,
            "value_type": "api_key",
            "secret_names": ["GLYPHHOLD_TOKEN"],
            "value": "hidden",
            "session_secret": "hidden",
            "authorization": "Bearer gh_live_hidden",
            "nested": {"encrypted_value": "hidden"},
        }
    )

    assert redacted["secrets_enabled"] is True
    assert redacted["value_type"] == "api_key"
    assert redacted["secret_names"] == ["GLYPHHOLD_TOKEN"]
    assert redacted["value"] == "[REDACTED]"
    assert redacted["session_secret"] == "[REDACTED]"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["nested"]["encrypted_value"] == "[REDACTED]"
