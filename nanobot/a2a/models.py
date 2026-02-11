from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

TaskState = Literal["submitted", "working", "completed", "failed", "canceled"]


class A2AError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class A2AErrorResponse(BaseModel):
    error: A2AError


class OperationResponse(BaseModel):
    status: str = "not_implemented"
    message: str


class TaskReference(BaseModel):
    id: str
    state: TaskState


class TaskResponse(BaseModel):
    task: TaskReference


class TaskListResponse(BaseModel):
    tasks: list[TaskReference] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class SendTaskMessage(BaseModel):
    role: str = "user"
    content: str
    content_type: str = "text/plain"


class SendTaskInput(BaseModel):
    messages: list[SendTaskMessage]


class SendTaskOptions(BaseModel):
    wait: bool = False
    timeout_ms: Optional[int] = None


class SendTaskRequest(BaseModel):
    method: str = "send"
    input: SendTaskInput
    options: SendTaskOptions = Field(default_factory=SendTaskOptions)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CancelTaskRequest(BaseModel):
    method: str = "cancel"
    reason: str = ""


class AgentCard(BaseModel):
    name: str
    description: str
    version: str
    protocol_version: str
    endpoints: dict[str, str]
    methods: list[str]
