from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, TypeVar, Union

from pydantic import BaseModel, ValidationError

from nanobot import __version__
from nanobot.config.schema import A2AConfig

from .models import (
    A2AError,
    A2AErrorResponse,
    AgentCard,
    AgentCardCapabilities,
    AgentCardSecurityScheme,
    AgentCardSkill,
    CancelTaskRequest,
    OperationResponse,
    SendTaskRequest,
)

T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True)
class RouteResult:
    status_code: int
    payload: dict[str, Any]


class A2ARouter:
    def __init__(self, config: A2AConfig):
        self._config = config

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes) -> RouteResult:
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

        if path.startswith("/a2a/") and not self._is_authorized(headers):
            return self._error(
                status_code=401, code="auth_required", message="Missing or invalid bearer token"
            )

        if method == "POST" and path == "/a2a/tasks:send":
            parsed = self._parse_json(body, SendTaskRequest)
            if isinstance(parsed, RouteResult):
                return parsed
            return self._placeholder("send")

        if method == "GET" and path == "/a2a/tasks":
            return self._placeholder("list")

        if method == "GET" and path.startswith("/a2a/tasks/") and not path.endswith(":cancel"):
            task_id = path.removeprefix("/a2a/tasks/")
            if not task_id:
                return self._error(status_code=404, code="task_not_found", message="Task not found")
            return self._placeholder("get")

        if method == "POST" and path.startswith("/a2a/tasks/") and path.endswith(":cancel"):
            parsed = self._parse_json(body, CancelTaskRequest)
            if isinstance(parsed, RouteResult):
                return parsed
            return self._placeholder("cancel")

        return self._error(status_code=404, code="method_not_found", message="Unsupported route")

    def _is_authorized(self, headers: dict[str, str]) -> bool:
        if not self._config.auth_token:
            return True
        auth_header = headers.get("authorization", "")
        expected = f"Bearer {self._config.auth_token}"
        return auth_header == expected

    def _parse_json(self, body: bytes, model_type: type[T]) -> Union[T, RouteResult]:
        if not body:
            return self._error(
                status_code=400, code="invalid_request", message="Request body is required"
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._error(status_code=400, code="parse_error", message="Invalid JSON payload")

        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            return self._error(
                status_code=400,
                code="invalid_params",
                message="Request payload failed validation",
                details={"errors": exc.errors()},
            )

    def _placeholder(self, method_name: str) -> RouteResult:
        response = OperationResponse(message=f"{method_name} route is not implemented yet")
        return RouteResult(status_code=501, payload=response.model_dump(mode="json"))

    def _error(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> RouteResult:
        response = A2AErrorResponse(
            error=A2AError(code=code, message=message, details=details or {})
        )
        return RouteResult(status_code=status_code, payload=response.model_dump(mode="json"))
