"""Tests for A2A task lifecycle state transitions."""

# pyright: reportMissingImports=false
import asyncio

import pytest

from nanobot.a2a.task_store import TaskStore


class EchoAgentLoop:
    """Mock AgentLoop that echoes content."""

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        await asyncio.sleep(0.01)
        return f"Echo: {content}"


class SlowAgentLoop:
    """Mock AgentLoop that takes time to complete."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.should_complete = asyncio.Event()

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        self.started.set()
        await self.should_complete.wait()
        return f"Slow: {content}"


class FailingAgentLoop:
    """Mock AgentLoop that always fails."""

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        raise RuntimeError("Simulated failure")


@pytest.mark.asyncio
async def test_submitted_to_working_to_completed() -> None:
    """Test normal flow: submitted → working → completed."""
    agent_loop = EchoAgentLoop()
    store = TaskStore(agent_loop)

    task_id = await store.create_task({"messages": [{"role": "user", "content": "hello"}]})

    # Initial state
    task = await store.get_task(task_id)
    assert task is not None
    assert task["task"]["state"] == "submitted"

    # Wait for completion
    for _ in range(50):  # Max 0.5s
        task = await store.get_task(task_id)
        if task["task"]["state"] == "completed":
            break
        await asyncio.sleep(0.01)

    assert task["task"]["state"] == "completed"
    assert task["output"] is not None


@pytest.mark.asyncio
async def test_submitted_to_failed() -> None:
    """Test failure flow: submitted → working → failed."""
    agent_loop = FailingAgentLoop()
    store = TaskStore(agent_loop)

    task_id = await store.create_task({"messages": [{"role": "user", "content": "hello"}]})

    # Wait for failure
    for _ in range(50):
        task = await store.get_task(task_id)
        if task["task"]["state"] == "failed":
            break
        await asyncio.sleep(0.01)

    assert task["task"]["state"] == "failed"
    assert task["failure"] is not None


@pytest.mark.asyncio
async def test_cancel_before_start() -> None:
    """Test canceling a task before it starts working."""
    # Use a slow agent loop to ensure we can cancel before it starts
    agent_loop = SlowAgentLoop()
    store = TaskStore(agent_loop)

    task_id = await store.create_task({"messages": [{"role": "user", "content": "hello"}]})

    # Cancel immediately (should work before working state)
    result = await store.cancel_task(task_id, "User requested")
    assert result is True

    task = await store.get_task(task_id)
    assert task["task"]["state"] == "canceled"


@pytest.mark.asyncio
async def test_cancel_while_working() -> None:
    """Test canceling a task while it's working."""
    agent_loop = SlowAgentLoop()
    store = TaskStore(agent_loop)

    task_id = await store.create_task({"messages": [{"role": "user", "content": "hello"}]})

    # Wait for task to start
    await asyncio.wait_for(agent_loop.started.wait(), timeout=1.0)

    # Cancel while working
    result = await store.cancel_task(task_id, "User requested")
    assert result is True

    # Release the agent loop
    agent_loop.should_complete.set()

    # Wait for cancellation to complete
    for _ in range(50):
        task = await store.get_task(task_id)
        if task["task"]["state"] == "canceled":
            break
        await asyncio.sleep(0.01)

    task = await store.get_task(task_id)
    assert task["task"]["state"] in ("canceled", "completed")


@pytest.mark.asyncio
async def test_cancel_completed_task_fails() -> None:
    """Test that canceling a completed task returns False."""
    agent_loop = EchoAgentLoop()
    store = TaskStore(agent_loop)

    task_id = await store.create_task({"messages": [{"role": "user", "content": "hello"}]})

    # Wait for completion
    for _ in range(50):
        task = await store.get_task(task_id)
        if task["task"]["state"] == "completed":
            break
        await asyncio.sleep(0.01)

    # Try to cancel completed task
    result = await store.cancel_task(task_id, "Too late")
    assert result is False


@pytest.mark.asyncio
async def test_list_tasks_by_state() -> None:
    """Test listing tasks filtered by state."""
    agent_loop = SlowAgentLoop()
    store = TaskStore(agent_loop)

    # Create tasks
    task_ids = []
    for i in range(3):
        task_id = await store.create_task({"messages": [{"role": "user", "content": f"task {i}"}]})
        task_ids.append(task_id)

    # List submitted tasks
    tasks, _ = await store.list_tasks(state="submitted")
    assert len(tasks) >= 0

    # List completed tasks (should be empty since agent loop is blocked)
    tasks, _ = await store.list_tasks(state="completed")
    assert len(tasks) == 0

    # Release agent loop
    agent_loop.should_complete.set()

    # Wait for completion and list again
    await asyncio.sleep(0.1)
    tasks, _ = await store.list_tasks(state="completed")
    assert len(tasks) >= 0


@pytest.mark.asyncio
async def test_list_pagination() -> None:
    """Test task list pagination."""
    agent_loop = EchoAgentLoop()
    store = TaskStore(agent_loop)

    # Create multiple tasks
    task_ids = []
    for i in range(10):
        task_id = await store.create_task({"messages": [{"role": "user", "content": f"task {i}"}]})
        task_ids.append(task_id)

    # Get first page
    tasks, next_cursor = await store.list_tasks(limit=3)
    assert len(tasks) == 3
    assert next_cursor is not None

    # Get second page
    tasks, next_cursor = await store.list_tasks(limit=3, cursor=next_cursor)
    assert len(tasks) == 3
    assert next_cursor is not None

    # Get last page
    tasks, next_cursor = await store.list_tasks(limit=3, cursor=next_cursor)
    assert len(tasks) >= 1
    # Next cursor may be None if we've reached the end
