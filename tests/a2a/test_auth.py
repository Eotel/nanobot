"""Tests for A2A authentication and authorization."""

# pyright: reportMissingImports=false

import pytest

from nanobot.a2a.router import A2ARouter
from nanobot.a2a.task_store import TaskStore
from nanobot.config.schema import A2AConfig


class TestAuthRequired:
    """Tests for endpoints requiring authentication."""

    @pytest.mark.asyncio
    async def test_send_rejects_missing_auth_when_configured(self) -> None:
        config = A2AConfig(enabled=True, auth_token="secret-token")
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle(
            "POST", "/a2a/tasks:send", {"content-type": "application/json"}, b"{}"
        )

        assert result.status_code == 401
        assert result.payload["error"]["code"] == "auth_required"

    @pytest.mark.asyncio
    async def test_send_rejects_invalid_auth_format(self) -> None:
        config = A2AConfig(enabled=True, auth_token="secret-token")
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle(
            "POST",
            "/a2a/tasks:send",
            {"content-type": "application/json", "authorization": "Basic dXNlcjpwYXNz"},
            b"{}",
        )

        assert result.status_code == 401
        assert result.payload["error"]["code"] == "auth_invalid"

    @pytest.mark.asyncio
    async def test_send_accepts_valid_auth(self) -> None:
        config = A2AConfig(enabled=True, auth_token="secret-token")
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle(
            "POST",
            "/a2a/tasks:send",
            {"content-type": "application/json", "authorization": "Bearer secret-token"},
            b'{"method":"send","input":{"messages":[]}}',
        )

        # Should not be auth error (may be successful or other errors like validation)
        if "error" in result.payload:
            assert result.payload["error"]["code"] != "auth_required"
            assert result.payload["error"]["code"] != "auth_invalid"


class TestDiscoveryAuth:
    """Tests for discovery endpoint authentication."""

    @pytest.mark.asyncio
    async def test_discovery_works_without_auth(self) -> None:
        config = A2AConfig(enabled=True, auth_token="secret-token")
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle("GET", "/.well-known/agent-card.json", {}, b"")

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_discovery_does_not_expose_token(self) -> None:
        config = A2AConfig(enabled=True, auth_token="secret-token")
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle("GET", "/.well-known/agent-card.json", {}, b"")

        # Token should not appear anywhere in response
        response_str = str(result.payload)
        assert "secret-token" not in response_str


class TestNoAuth:
    """Tests when auth is not configured."""

    @pytest.mark.asyncio
    async def test_endpoints_work_without_auth_when_not_configured(self) -> None:
        config = A2AConfig(enabled=True, auth_token="")
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle(
            "POST", "/a2a/tasks:send", {"content-type": "application/json"}, b"{}"
        )

        # Should not be auth error
        assert result.payload["error"]["code"] != "auth_required"
        assert result.payload["error"]["code"] != "auth_invalid"
