# pyright: reportMissingImports=false
import asyncio
from typing import Any

import pytest

from nanobot.a2a.task_store import TaskStateTransitionError, TaskStore


async def _wait_for_terminal_state(
    store: TaskStore, task_id: str, timeout: float = 1.0
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        task = await store.get_task(task_id)
        assert task is not None
        if task["task"]["state"] in {"completed", "failed", "canceled"}:
            return task
        await asyncio.sleep(0.01)
    raise TimeoutError(f"Task {task_id} did not reach a terminal state")


class EchoAgentLoop:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        self.calls.append(
            {
                "content": content,
                "session_key": session_key,
                "channel": channel,
                "chat_id": chat_id,
            }
        )
        await asyncio.sleep(0)
        return f"echo: {content}"


class SlowAgentLoop:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        self.started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return f"slow: {content}"


@pytest.mark.asyncio
async def test_create_and_get_task_initial_state() -> None:
    store = TaskStore()

    task_id = await store.create_task({"messages": [{"role": "user", "content": "hello"}]})

    task = await store.get_task(task_id)
    assert task is not None
    assert task["task"]["id"] == task_id
    assert task["task"]["state"] == "submitted"
    assert task["output"] is None
    assert task["failure"] is None
    assert len(task_id) == 8


@pytest.mark.asyncio
async def test_valid_and_invalid_state_transitions() -> None:
    store = TaskStore()
    task_id = await store.create_task({"messages": [{"role": "user", "content": "hello"}]})

    await store.update_task_state(task_id, "working")
    await store.update_task_state(
        task_id,
        "completed",
        output={
            "messages": [
                {
                    "role": "assistant",
                    "content": "done",
                    "content_type": "text/plain",
                }
            ]
        },
    )

    with pytest.raises(TaskStateTransitionError):
        await store.update_task_state(task_id, "working")


@pytest.mark.asyncio
async def test_list_tasks_with_state_filter_and_cursor_pagination() -> None:
    store = TaskStore()
    ids = []
    for idx in range(3):
        ids.append(
            await store.create_task({"messages": [{"role": "user", "content": f"msg-{idx}"}]})
        )

    await store.update_task_state(ids[0], "working")
    await store.update_task_state(ids[0], "completed")

    page1, next_cursor = await store.list_tasks(limit=2)
    assert [task["id"] for task in page1] == ids[:2]
    assert next_cursor == ids[1]

    page2, page2_cursor = await store.list_tasks(limit=2, cursor=next_cursor)
    assert [task["id"] for task in page2] == [ids[2]]
    assert page2_cursor is None

    completed, _ = await store.list_tasks(state="completed")
    assert [task["id"] for task in completed] == [ids[0]]


@pytest.mark.asyncio
async def test_cancel_before_start_moves_task_to_canceled() -> None:
    store = TaskStore()
    task_id = await store.create_task({"messages": [{"role": "user", "content": "hello"}]})

    cancelled = await store.cancel_task(task_id, "User requested cancellation")

    assert cancelled is True
    task = await store.get_task(task_id)
    assert task is not None
    assert task["task"]["state"] == "canceled"
    assert task["failure"]["code"] == "task_canceled"

    with pytest.raises(TaskStateTransitionError):
        await store.update_task_state(task_id, "working")


@pytest.mark.asyncio
async def test_task_store_delegates_execution_to_agent_loop() -> None:
    agent_loop = EchoAgentLoop()
    store = TaskStore(agent_loop=agent_loop)

    task_id = await store.create_task({"messages": [{"role": "user", "content": "summarize this"}]})
    task = await _wait_for_terminal_state(store, task_id)

    assert task["task"]["state"] == "completed"
    assert task["output"] is not None
    assert task["output"]["messages"][0]["content"] == "echo: summarize this"
    assert len(agent_loop.calls) == 1
    assert agent_loop.calls[0]["session_key"] == f"a2a:{task_id}"


@pytest.mark.asyncio
async def test_cancel_running_task_handles_race_safely() -> None:
    agent_loop = SlowAgentLoop()
    store = TaskStore(agent_loop=agent_loop)

    task_id = await store.create_task({"messages": [{"role": "user", "content": "long running"}]})
    await asyncio.wait_for(agent_loop.started.wait(), timeout=1.0)

    cancelled = await store.cancel_task(task_id, "User requested cancellation")
    assert cancelled is True

    task = await _wait_for_terminal_state(store, task_id)
    assert task["task"]["state"] in {"canceled", "completed"}
    if task["task"]["state"] == "canceled":
        assert task["failure"]["code"] == "task_canceled"
