from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

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


class AgentCardCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    streaming: bool = False
    push_notifications: bool = Field(default=False, alias="pushNotifications")


class AgentCardSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


class AgentCardSecurityScheme(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["http"] = "http"
    scheme: Literal["bearer"] = "bearer"
    bearer_format: str = Field(default="token", alias="bearerFormat")
    description: str = "Bearer token authentication"


class AgentCard(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str
    version: str
    protocol_version: str
    endpoints: dict[str, str]
    methods: list[str]
    capabilities: AgentCardCapabilities
    default_input_modes: list[str] = Field(default_factory=list, alias="defaultInputModes")
    default_output_modes: list[str] = Field(default_factory=list, alias="defaultOutputModes")
    skills: list[AgentCardSkill] = Field(default_factory=list)
    security_schemes: dict[str, AgentCardSecurityScheme] = Field(
        default_factory=dict,
        alias="securitySchemes",
    )
    security: list[dict[str, list[str]]] = Field(default_factory=list)
