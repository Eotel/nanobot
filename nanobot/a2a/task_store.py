from __future__ import annotations

import asyncio
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Protocol

from nanobot.a2a.models import TaskState


logger = logging.getLogger(__name__)


class AgentLoopExecutor(Protocol):
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str: ...


class TaskStateTransitionError(ValueError):
    pass


TERMINAL_STATES: set[TaskState] = {"completed", "failed", "canceled"}
ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    "submitted": {"working", "canceled"},
    "working": {"completed", "failed", "canceled"},
    "completed": set(),
    "failed": set(),
    "canceled": set(),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TaskStore:
    def __init__(self, agent_loop: AgentLoopExecutor | None = None):
        self._agent_loop = agent_loop
        self._lock = asyncio.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._task_order: list[str] = []
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

    async def create_task(self, input_data: dict[str, Any]) -> str:
        task_id = str(uuid.uuid4())[:8]
        now = _now_iso()
        task_record = {
            "task": {
                "id": task_id,
                "state": "submitted",
                "created_at": now,
                "updated_at": now,
                "metadata": {},
            },
            "input": deepcopy(input_data),
            "output": None,
            "failure": None,
            "cancel_reason": "",
            "cancel_requested": False,
        }

        async with self._lock:
            self._tasks[task_id] = task_record
            self._task_order.append(task_id)

            if self._agent_loop is not None:
                task = asyncio.create_task(self._run_task(task_id), name=f"a2a-task-{task_id}")
                self._running_tasks[task_id] = task

        return task_id

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return deepcopy(task) if task else None

    async def list_tasks(
        self,
        state: TaskState | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        bounded_limit = max(1, min(limit, 100))

        async with self._lock:
            task_ids = [
                task_id
                for task_id in self._task_order
                if state is None or self._tasks[task_id]["task"]["state"] == state
            ]

            start = 0
            if cursor and cursor in task_ids:
                start = task_ids.index(cursor) + 1

            page_ids = task_ids[start : start + bounded_limit]
            tasks = [deepcopy(self._tasks[task_id]["task"]) for task_id in page_ids]

            next_cursor = None
            if start + bounded_limit < len(task_ids):
                next_cursor = page_ids[-1]

            return tasks, next_cursor

    async def cancel_task(self, task_id: str, reason: str) -> bool:
        running_task: asyncio.Task[None] | None = None

        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False

            current_state: TaskState = task["task"]["state"]
            if current_state == "canceled":
                return True

            if current_state in {"completed", "failed"}:
                return False

            task["cancel_requested"] = True
            task["cancel_reason"] = reason
            task["failure"] = self._build_cancel_failure(reason)

            if current_state == "submitted":
                self._apply_state_transition(task, "canceled")
                return True

            self._apply_state_transition(task, "canceled")
            running_task = self._running_tasks.get(task_id)

        if running_task is not None:
            running_task.cancel()

        return True

    async def update_task_state(
        self,
        task_id: str,
        new_state: TaskState,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"Task {task_id} not found")

            self._apply_state_transition(task, new_state)

            if output is not None:
                task["output"] = deepcopy(output)

            if error is not None:
                task["failure"] = deepcopy(error)

            if new_state in TERMINAL_STATES:
                self._running_tasks.pop(task_id, None)

    async def _run_task(self, task_id: str) -> None:
        if self._agent_loop is None:
            return

        try:
            async with self._lock:
                task = self._tasks.get(task_id)
                if task is None:
                    return
                if task["task"]["state"] != "submitted":
                    return

                self._apply_state_transition(task, "working")
                content = self._extract_content(task["input"])

            output_text = await self._agent_loop.process_direct(
                content,
                session_key=f"a2a:{task_id}",
                channel="a2a",
                chat_id=task_id,
            )

            await self.update_task_state(
                task_id,
                "completed",
                output={
                    "messages": [
                        {
                            "role": "assistant",
                            "content": output_text,
                            "content_type": "text/plain",
                        }
                    ]
                },
            )

        except asyncio.CancelledError:
            await self._mark_canceled_if_possible(task_id)
            raise
        except TaskStateTransitionError as exc:
            logger.warning(f"Task {task_id} transition blocked during execution: {exc}")
        except Exception as exc:
            logger.exception(f"Task {task_id} failed: {exc}")
            failure = {
                "code": "task_execution_failed",
                "message": "Task execution failed",
                "details": {"error": str(exc)},
            }

            try:
                await self.update_task_state(task_id, "failed", error=failure)
            except TaskStateTransitionError as transition_exc:
                logger.warning(
                    f"Task {task_id} transition blocked while marking failure: {transition_exc}"
                )
        finally:
            async with self._lock:
                self._running_tasks.pop(task_id, None)

    async def _mark_canceled_if_possible(self, task_id: str) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return

            if task["task"]["state"] == "working":
                task["failure"] = self._build_cancel_failure(task.get("cancel_reason", ""))
                self._apply_state_transition(task, "canceled")

    def _apply_state_transition(self, task: dict[str, Any], new_state: TaskState) -> None:
        current_state: TaskState = task["task"]["state"]
        if current_state == new_state:
            return

        if new_state not in ALLOWED_TRANSITIONS[current_state]:
            msg = f"Invalid task state transition: {current_state} -> {new_state}"
            logger.error(msg)
            raise TaskStateTransitionError(msg)

        task["task"]["state"] = new_state
        task["task"]["updated_at"] = _now_iso()

    def _extract_content(self, input_data: dict[str, Any]) -> str:
        messages = input_data.get("messages") if isinstance(input_data, dict) else None
        if not isinstance(messages, list):
            raise ValueError("Task input must contain a messages list")

        for msg in reversed(messages):
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                return msg["content"]

        if messages and isinstance(messages[0].get("content"), str):
            return messages[0]["content"]

        raise ValueError("Task input does not include text content")

    def _build_cancel_failure(self, reason: str) -> dict[str, Any]:
        message = reason or "Task canceled"
        return {
            "code": "task_canceled",
            "message": message,
            "details": {"reason": reason},
        }
