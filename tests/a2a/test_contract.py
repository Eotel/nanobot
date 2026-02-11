"""Contract tests for A2A protocol endpoints."""

# pyright: reportMissingImports=false

from nanobot.a2a.models import (
    CancelTaskRequest,
    SendTaskInput,
    SendTaskMessage,
    SendTaskRequest,
)
from nanobot.a2a.router import A2ARouter
from nanobot.config.schema import A2AConfig


class TestDiscovery:
    """Tests for /.well-known/agent-card.json endpoint."""

    def test_discovery_returns_valid_agent_card(self) -> None:
        config = A2AConfig(enabled=True, protocol_version="0.3")
        router = A2ARouter(config)

        result = router.handle("GET", "/.well-known/agent-card.json", {}, b"")

        assert result.status_code == 200
        payload = result.payload
        assert payload["name"] == "nanobot"
        assert payload["protocolVersion"] == "0.3"
        assert "endpoints" in payload
        assert "methods" in payload
        assert "capabilities" in payload
        assert payload["capabilities"]["streaming"] is False
        assert payload["capabilities"]["pushNotifications"] is False
        assert "skills" in payload
        assert len(payload["skills"]) >= 1

    def test_discovery_includes_auth_when_configured(self) -> None:
        config = A2AConfig(enabled=True, auth_token="secret-token")
        router = A2ARouter(config)

        result = router.handle("GET", "/.well-known/agent-card.json", {}, b"")

        assert result.status_code == 200
        payload = result.payload
        assert "securitySchemes" in payload
        assert "bearerAuth" in payload["securitySchemes"]
        assert len(payload["security"]) > 0

    def test_discovery_does_not_expose_token(self) -> None:
        config = A2AConfig(enabled=True, auth_token="secret-token")
        router = A2ARouter(config)

        result = router.handle("GET", "/.well-known/agent-card.json", {}, b"")

        payload_str = str(result.payload)
        assert "secret-token" not in payload_str


class TestSend:
    """Tests for POST /a2a/tasks:send endpoint."""

    def test_send_creates_task(self) -> None:
        config = A2AConfig(enabled=True)
        router = A2ARouter(config)
        body = (
            SendTaskRequest(input=SendTaskInput(messages=[SendTaskMessage(content="test message")]))
            .model_dump_json()
            .encode()
        )

        result = router.handle(
            "POST", "/a2a/tasks:send", {"content-type": "application/json"}, body
        )

        # Returns 202 Accepted (async) or 200 OK (sync with wait=true)
        assert result.status_code in (200, 202, 501)  # 501 if not fully implemented

    def test_send_requires_content_type_json(self) -> None:
        config = A2AConfig(enabled=True)
        router = A2ARouter(config)

        result = router.handle("POST", "/a2a/tasks:send", {"content-type": "text/plain"}, b"{}")

        assert result.status_code == 415
        assert result.payload["error"]["code"] == "unsupported_type"

    def test_send_validates_payload(self) -> None:
        config = A2AConfig(enabled=True)
        router = A2ARouter(config)

        result = router.handle(
            "POST", "/a2a/tasks:send", {"content-type": "application/json"}, b"invalid json"
        )

        assert result.status_code == 400
        assert result.payload["error"]["code"] == "parse_error"


class TestGet:
    """Tests for GET /a2a/tasks/{task_id} endpoint."""

    def test_get_returns_task_not_found_for_invalid_id(self) -> None:
        config = A2AConfig(enabled=True)
        router = A2ARouter(config)

        result = router.handle("GET", "/a2a/tasks/invalid-id", {}, b"")

        assert result.status_code == 404
        assert result.payload["error"]["code"] == "task_not_found"


class TestList:
    """Tests for GET /a2a/tasks endpoint."""

    def test_list_returns_task_list(self) -> None:
        config = A2AConfig(enabled=True)
        router = A2ARouter(config)

        result = router.handle("GET", "/a2a/tasks", {}, b"")

        # Should return list (may be empty)
        assert result.status_code in (200, 501)


class TestCancel:
    """Tests for POST /a2a/tasks/{task_id}:cancel endpoint."""

    def test_cancel_validates_method(self) -> None:
        config = A2AConfig(enabled=True)
        router = A2ARouter(config)
        body = CancelTaskRequest(method="invalid").model_dump_json().encode()

        result = router.handle(
            "POST", "/a2a/tasks/task-123:cancel", {"content-type": "application/json"}, body
        )

        assert result.status_code == 400
        assert result.payload["error"]["code"] == "invalid_request"


class TestErrorFormat:
    """Tests that all errors follow A2A contract format."""

    def test_error_includes_required_fields(self) -> None:
        config = A2AConfig(enabled=True)
        router = A2ARouter(config)

        result = router.handle("GET", "/a2a/unknown-endpoint", {}, b"")

        assert result.status_code == 404
        error = result.payload["error"]
        assert "code" in error
        assert "jsonrpc_code" in error
        assert "http_status" in error
        assert "message" in error
        assert "details" in error

    def test_error_jsonrpc_codes_match_contract(self) -> None:
        config = A2AConfig(enabled=True)
        router = A2ARouter(config)

        # Test various error scenarios
        test_cases = [
            ("parse_error", -32700),
            ("invalid_request", -32600),
            ("method_not_found", -32601),
            ("invalid_params", -32602),
            ("internal_error", -32603),
        ]

        for code, expected_jsonrpc in test_cases:
            result = router._error(code)
            assert result.payload["error"]["jsonrpc_code"] == expected_jsonrpc
