from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional, Protocol, TypeVar, Union

from pydantic import BaseModel, ValidationError

from nanobot import __version__
from nanobot.config.schema import A2AConfig

from .models import (
    AgentCard,
    AgentCardCapabilities,
    AgentCardSecurityScheme,
    AgentCardSkill,
    CancelTaskRequest,
    SendTaskRequest,
    TaskState,
)

T = TypeVar("T", bound=BaseModel)

TERMINAL_STATES: set[TaskState] = {"completed", "failed", "canceled"}
VALID_TASK_STATES: set[TaskState] = {
    "submitted",
    "working",
    "completed",
    "failed",
    "canceled",
}


class TaskStoreLike(Protocol):
    async def create_task(self, input_data: dict[str, Any]) -> str: ...

    async def get_task(self, task_id: str) -> dict[str, Any] | None: ...

    async def list_tasks(
        self,
        state: TaskState | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    async def cancel_task(self, task_id: str, reason: str) -> bool: ...


ERROR_MAP: dict[str, tuple[int, int, str]] = {
    "parse_error": (400, -32700, "Invalid JSON payload"),
    "invalid_request": (400, -32600, "Invalid request"),
    "method_not_found": (404, -32601, "Unsupported route"),
    "invalid_params": (400, -32602, "Request payload failed validation"),
    "internal_error": (500, -32603, "Internal server error"),
    "auth_required": (401, -32001, "Missing bearer token"),
    "auth_invalid": (401, -32002, "Invalid bearer token"),
    "forbidden": (403, -32003, "Forbidden"),
    "task_not_found": (404, -32004, "Task not found"),
    "task_not_cancelable": (409, -32005, "Task not cancelable"),
    "unsupported_type": (415, -32006, "Content-Type must be application/json"),
    "rate_limited": (429, -32007, "Rate limit exceeded"),
    "upstream_timeout": (504, -32008, "Request processing timed out"),
    "payload_too_large": (413, -32007, "Request body exceeds limit"),
}

SENSITIVE_DETAIL_KEYS = {
    "authorization",
    "auth_token",
    "token",
    "password",
    "secret",
    "api_key",
}


@dataclass
class RouteResult:
    status_code: int
    payload: dict[str, Any]


class A2ARouter:
    def __init__(self, config: A2AConfig, task_store: TaskStoreLike):
        self._config = config
        self._task_store = task_store

    async def handle(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
        query_params: Optional[dict[str, list[str]]] = None,
    ) -> RouteResult:
        if method == "GET" and path == "/a2a/health":
            return RouteResult(status_code=200, payload={"status": "ok"})

        if method == "GET" and path == "/.well-known/agent-card.json":
            security_schemes: dict[str, AgentCardSecurityScheme] = {}
            security: list[dict[str, list[str]]] = []
            if self._config.auth_token:
                security_schemes["bearerAuth"] = AgentCardSecurityScheme()
                security.append({"bearerAuth": []})

            card = AgentCard(
                name="nanobot",
                description="Ultra-lightweight personal AI assistant with A2A HTTP+JSON MVP support",
                version=__version__,
                protocol_version=self._config.protocol_version,
                endpoints={
                    "send": "/a2a/tasks:send",
                    "get": "/a2a/tasks/{task_id}",
                    "list": "/a2a/tasks",
                    "cancel": "/a2a/tasks/{task_id}:cancel",
                },
                methods=["send", "get", "list", "cancel"],
                capabilities=AgentCardCapabilities(streaming=False, pushNotifications=False),
                defaultInputModes=["text/plain"],
                defaultOutputModes=["text/plain"],
                skills=[
                    AgentCardSkill(
                        id="nanobot-text-assistant",
                        name="nanobot",
                        description="Text-only assistant for A2A MVP task handling",
                        tags=["assistant", "text"],
                    )
                ],
                securitySchemes=security_schemes,
                security=security,
            )
            return RouteResult(status_code=200, payload=card.model_dump(mode="json", by_alias=True))

        if path.startswith("/a2a/"):
            auth_error = self._auth_error(headers)
            if auth_error is not None:
                return self._error(code=auth_error[0], message=auth_error[1])

            if self._is_rate_limited(headers):
                return self._error(code="rate_limited")

            content_type_error = self._validate_content_type(
                method=method, path=path, headers=headers
            )
            if content_type_error is not None:
                return content_type_error

        if method == "POST" and path == "/a2a/tasks:send":
            parsed = self._parse_json(body, SendTaskRequest)
            if isinstance(parsed, RouteResult):
                return parsed
            if parsed.method != "send":
                return self._error(code="invalid_request", message="Method must be 'send'")
            content_type_error = self._validate_send_content_types(parsed)
            if content_type_error is not None:
                return content_type_error
            return await self._handle_send(parsed)

        if method == "GET" and path == "/a2a/tasks":
            return await self._handle_list(query_params or {})

        if method == "GET" and path.startswith("/a2a/tasks/") and not path.endswith(":cancel"):
            task_id = self._extract_task_id(path)
            if not task_id:
                return self._error(code="task_not_found")
            return await self._handle_get(task_id)

        if method == "POST" and path.startswith("/a2a/tasks/") and path.endswith(":cancel"):
            parsed = self._parse_json(body, CancelTaskRequest)
            if isinstance(parsed, RouteResult):
                return parsed
            if parsed.method != "cancel":
                return self._error(code="invalid_request", message="Method must be 'cancel'")
            task_id = self._extract_task_id(path, suffix=":cancel")
            if not task_id:
                return self._error(code="task_not_found")
            return await self._handle_cancel(task_id=task_id, request=parsed)

        return self._error(code="method_not_found")

    def error_response(
        self,
        code: str,
        message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        status_code: Optional[int] = None,
    ) -> RouteResult:
        return self._error(code=code, message=message, details=details, status_code=status_code)

    def _auth_error(self, headers: dict[str, str]) -> Optional[tuple[str, str]]:
        if not self._config.auth_token:
            return None

        auth_header = headers.get("authorization", "").strip()
        if not auth_header:
            return ("auth_required", "Missing bearer token")

        scheme, separator, token = auth_header.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            return ("auth_invalid", "Invalid bearer token")

        if not secrets.compare_digest(token, self._config.auth_token):
            return ("auth_invalid", "Invalid bearer token")
        return None

    def _is_rate_limited(self, headers: dict[str, str]) -> bool:
        _ = headers
        return False

    def _validate_content_type(
        self, method: str, path: str, headers: dict[str, str]
    ) -> Optional[RouteResult]:
        if method != "POST" or not path.startswith("/a2a/"):
            return None

        content_type = headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type == "application/json":
            return None

        return self._error(
            code="unsupported_type",
            details={
                "expected_content_type": "application/json",
                "received_content_type": media_type,
            },
        )

    def _validate_send_content_types(self, request: SendTaskRequest) -> Optional[RouteResult]:
        allowed_types = {"text/plain", "text/markdown"}
        for message in request.input.messages:
            if message.content_type not in allowed_types:
                return self._error(
                    code="unsupported_type",
                    message="MVP supports text/plain and text/markdown only",
                    details={"received_content_type": message.content_type},
                )
        return None

    def _parse_json(self, body: bytes, model_type: type[T]) -> Union[T, RouteResult]:
        if not body:
            return self._error(code="invalid_request", message="Request body is required")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._error(code="parse_error")

        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            return self._error(
                code="invalid_params",
                details={"errors": self._sanitize_validation_errors(exc.errors())},
            )

    def _sanitize_validation_errors(self, errors: Sequence[object]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for error in errors:
            if not isinstance(error, dict):
                sanitized.append(
                    {
                        "type": "validation_error",
                        "loc": (),
                        "msg": "Invalid value",
                    }
                )
                continue
            item: dict[str, Any] = {
                "type": error.get("type", "validation_error"),
                "loc": error.get("loc", ()),
                "msg": error.get("msg", "Invalid value"),
            }
            if isinstance(error.get("ctx"), dict):
                item["ctx"] = {
                    key: value
                    for key, value in error["ctx"].items()
                    if key not in {"error", "input", "value"}
                }
            sanitized.append(item)
        return sanitized

    async def _handle_send(self, request: SendTaskRequest) -> RouteResult:
        task_payload = request.model_dump(mode="json")

        try:
            task_id = await self._task_store.create_task(task_payload)
            task_record = await self._task_store.get_task(task_id)
        except Exception:
            return self._error(code="internal_error")

        if task_record is None:
            return self._error(code="internal_error")

        if request.options.wait:
            timeout_ms = request.options.timeout_ms or 30000
            completed_task = await self._wait_for_terminal_state(
                task_id=task_id, timeout_ms=timeout_ms
            )
            if completed_task is not None:
                return RouteResult(
                    status_code=200,
                    payload=self._build_send_response(completed_task),
                )

            latest_task = await self._task_store.get_task(task_id)
            if latest_task is not None:
                return RouteResult(
                    status_code=202,
                    payload=self._build_send_response(latest_task),
                )

        return RouteResult(status_code=202, payload=self._build_send_response(task_record))

    async def _handle_get(self, task_id: str) -> RouteResult:
        try:
            task_record = await self._task_store.get_task(task_id)
        except Exception:
            return self._error(code="internal_error")

        if task_record is None:
            return self._error(code="task_not_found")

        return RouteResult(status_code=200, payload=self._build_get_response(task_record))

    async def _handle_list(self, query_params: dict[str, list[str]]) -> RouteResult:
        state_raw = self._query_param_value(query_params, "state")
        limit_raw = self._query_param_value(query_params, "limit")
        cursor = self._query_param_value(query_params, "cursor")

        state: TaskState | None = None
        if state_raw:
            if state_raw not in VALID_TASK_STATES:
                return self._error(
                    code="invalid_params",
                    details={"state": state_raw, "allowed": sorted(VALID_TASK_STATES)},
                )
            state = state_raw

        limit = 20
        if limit_raw:
            try:
                limit = int(limit_raw)
            except ValueError:
                return self._error(code="invalid_params", details={"limit": limit_raw})
            if limit <= 0:
                return self._error(code="invalid_params", details={"limit": limit_raw})

        try:
            tasks, next_cursor = await self._task_store.list_tasks(
                state=state,
                limit=limit,
                cursor=cursor,
            )
        except Exception:
            return self._error(code="internal_error")

        return RouteResult(
            status_code=200,
            payload={
                "tasks": tasks,
                "next_cursor": next_cursor,
            },
        )

    async def _handle_cancel(self, task_id: str, request: CancelTaskRequest) -> RouteResult:
        try:
            task_record = await self._task_store.get_task(task_id)
            if task_record is None:
                return self._error(code="task_not_found")

            await self._task_store.cancel_task(task_id, request.reason)
            updated_task = await self._task_store.get_task(task_id)
        except Exception:
            return self._error(code="internal_error")

        if updated_task is None:
            return self._error(code="task_not_found")

        return RouteResult(status_code=200, payload={"task": updated_task["task"]})

    async def _wait_for_terminal_state(
        self,
        task_id: str,
        timeout_ms: int,
    ) -> dict[str, Any] | None:
        if timeout_ms <= 0:
            return await self._task_store.get_task(task_id)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + (timeout_ms / 1000)

        while True:
            task_record = await self._task_store.get_task(task_id)
            if task_record is None:
                return None

            state = task_record.get("task", {}).get("state")
            if state in TERMINAL_STATES:
                return task_record

            remaining = deadline - loop.time()
            if remaining <= 0:
                return None

            await asyncio.sleep(min(0.05, remaining))

    def _extract_task_id(self, path: str, suffix: str = "") -> str:
        prefix = "/a2a/tasks/"
        if not path.startswith(prefix):
            return ""

        task_id = path[len(prefix) :]
        if suffix:
            if not task_id.endswith(suffix):
                return ""
            task_id = task_id[: -len(suffix)]
        return task_id.strip()

    def _query_param_value(self, query_params: dict[str, list[str]], name: str) -> Optional[str]:
        values = query_params.get(name)
        if not values:
            return None
        value = values[-1].strip()
        return value or None

    def _build_send_response(self, task_record: dict[str, Any]) -> dict[str, Any]:
        return {
            "task": task_record["task"],
            "output": task_record.get("output"),
        }

    def _build_get_response(self, task_record: dict[str, Any]) -> dict[str, Any]:
        return {
            "task": task_record["task"],
            "output": task_record.get("output"),
            "failure": task_record.get("failure"),
        }

    def _error(
        self,
        code: str,
        message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        status_code: Optional[int] = None,
    ) -> RouteResult:
        default_status, jsonrpc_code, default_message = ERROR_MAP.get(
            code, ERROR_MAP["internal_error"]
        )
        resolved_status = status_code if status_code is not None else default_status
        resolved_message = message or default_message
        payload = {
            "error": {
                "code": code,
                "jsonrpc_code": jsonrpc_code,
                "http_status": resolved_status,
                "message": resolved_message,
                "details": self._sanitize_details(details),
            }
        }
        return RouteResult(status_code=resolved_status, payload=payload)

    def _sanitize_details(self, details: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not details:
            return {}

        sanitized: dict[str, Any] = {}
        for key, value in details.items():
            key_str = str(key)
            if key_str.lower() in SENSITIVE_DETAIL_KEYS:
                continue
            sanitized[key_str] = self._sanitize_value(value)
        return sanitized

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [self._sanitize_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize_value(item) for item in value]
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                key_str = str(key)
                if key_str.lower() in SENSITIVE_DETAIL_KEYS:
                    continue
                sanitized[key_str] = self._sanitize_value(item)
            return sanitized
        return str(value)
