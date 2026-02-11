"""Integration tests for A2A protocol."""

# pyright: reportMissingImports=false
import asyncio
from unittest.mock import MagicMock

import pytest

from nanobot.a2a.models import (
    CancelTaskRequest,
    SendTaskInput,
    SendTaskMessage,
    SendTaskRequest,
)
from nanobot.a2a.router import A2ARouter
from nanobot.a2a.server import A2AServer
from nanobot.a2a.task_store import TaskStore
from nanobot.config.schema import A2AConfig


class EchoAgentLoop:
    """Mock AgentLoop that echoes content."""

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        await asyncio.sleep(0.01)  # Simulate async work
        return f"Echo: {content}"


@pytest.mark.asyncio
async def test_full_task_lifecycle() -> None:
    """Test complete flow: send → get → list → cancel."""
    config = A2AConfig(enabled=True)
    agent_loop = EchoAgentLoop()
    task_store = TaskStore(agent_loop)
    router = A2ARouter(config, task_store)

    # Send task
    body = (
        SendTaskRequest(input=SendTaskInput(messages=[SendTaskMessage(content="hello")]))
        .model_dump_json()
        .encode()
    )

    result = await router.handle(
        "POST", "/a2a/tasks:send", {"content-type": "application/json"}, body
    )

    assert result.status_code == 202
    task_id = result.payload["task"]["id"]

    # Get task
    result = await router.handle("GET", f"/a2a/tasks/{task_id}", {}, b"")
    assert result.status_code == 200
    assert result.payload["task"]["id"] == task_id

    # List tasks
    result = await router.handle("GET", "/a2a/tasks", {}, b"")
    assert result.status_code == 200
    assert len(result.payload["tasks"]) >= 1

    # Cancel task
    cancel_body = CancelTaskRequest(method="cancel").model_dump_json().encode()
    result = await router.handle(
        "POST", f"/a2a/tasks/{task_id}:cancel", {"content-type": "application/json"}, cancel_body
    )

    # Task may already be completed, so cancel might fail
    assert result.status_code in (200, 409)


@pytest.mark.asyncio
async def test_concurrent_tasks() -> None:
    """Test creating multiple tasks concurrently."""
    config = A2AConfig(enabled=True)
    agent_loop = EchoAgentLoop()
    task_store = TaskStore(agent_loop)
    router = A2ARouter(config, task_store)

    # Create multiple tasks
    task_ids = []
    for i in range(5):
        body = (
            SendTaskRequest(input=SendTaskInput(messages=[SendTaskMessage(content=f"task {i}")]))
            .model_dump_json()
            .encode()
        )

        result = await router.handle(
            "POST", "/a2a/tasks:send", {"content-type": "application/json"}, body
        )

        if result.status_code == 202:
            task_ids.append(result.payload["task"]["id"])

    # All tasks should exist
    assert len(task_ids) > 0

    # List should return all tasks
    result = await router.handle("GET", "/a2a/tasks", {}, b"")
    assert result.status_code == 200
    returned_ids = {t["id"] for t in result.payload["tasks"]}

    for task_id in task_ids:
        assert task_id in returned_ids


class TestErrorScenarios:
    """Test various error scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_json_payload(self) -> None:
        config = A2AConfig(enabled=True)
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle(
            "POST", "/a2a/tasks:send", {"content-type": "application/json"}, b"not json"
        )

        assert result.status_code == 400
        assert result.payload["error"]["code"] == "parse_error"

    @pytest.mark.asyncio
    async def test_missing_required_fields(self) -> None:
        config = A2AConfig(enabled=True)
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle(
            "POST", "/a2a/tasks:send", {"content-type": "application/json"}, b'{"method":"send"}'
        )

        assert result.status_code == 400
        assert result.payload["error"]["code"] == "invalid_params"

    @pytest.mark.asyncio
    async def test_unknown_endpoint(self) -> None:
        config = A2AConfig(enabled=True)
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        result = await router.handle("GET", "/a2a/unknown", {}, b"")

        assert result.status_code == 404
        assert result.payload["error"]["code"] == "method_not_found"

    @pytest.mark.asyncio
    async def test_invalid_task_id_format(self) -> None:
        config = A2AConfig(enabled=True)
        task_store = TaskStore()
        router = A2ARouter(config, task_store)

        # Various invalid task ID formats
        invalid_ids = ["", "   ", "/../etc/passwd", "task with spaces"]

        for task_id in invalid_ids:
            result = await router.handle("GET", f"/a2a/tasks/{task_id}", {}, b"")
            # Should return 404 for invalid IDs
            assert result.status_code == 404


@pytest.mark.asyncio
async def test_a2a_server_receives_agent_loop():
    """Regression test: AgentLoop must be wired to A2AServer."""
    config = A2AConfig(enabled=True, host="127.0.0.1", port=9999)
    mock_agent = MagicMock()

    server = A2AServer(config, agent_loop=mock_agent)

    # Verify agent_loop reached TaskStore
    assert server.task_store._agent_loop is mock_agent
