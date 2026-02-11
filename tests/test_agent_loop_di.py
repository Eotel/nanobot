import copy
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ExecToolConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import Session, SessionManager


class FakeProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse] | None = None):
        super().__init__()
        self.responses = responses or [LLMResponse(content="ok")]
        self.call_count = 0
        self.default_model = "fake-model"
        self.default_model_calls = 0
        self.chat_calls: list[dict[str, Any]] = []

    def get_default_model(self) -> str:
        self.default_model_calls += 1
        return self.default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.chat_calls.append(
            {
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
                "model": model,
                "kwargs": {"max_tokens": max_tokens, "temperature": temperature},
            }
        )
        idx = min(self.call_count, len(self.responses) - 1)
        self.call_count += 1
        return self.responses[idx]


class FakeSessionManager(SessionManager):
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.saved: list[Session] = []
        self.requested_keys: list[str] = []

    def get_or_create(self, key: str) -> Session:
        self.requested_keys.append(key)
        if key not in self.sessions:
            self.sessions[key] = Session(key=key)
        return self.sessions[key]

    def save(self, session: Session) -> None:
        self.saved.append(session)


def _new_loop(
    tmp_path: Path,
    provider: FakeProvider | None = None,
    session_manager: SessionManager | None = None,
    **kwargs,
) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=provider or FakeProvider(),
        workspace=tmp_path,
        session_manager=session_manager,
        **kwargs,
    )


def test_constructor_default_model(tmp_path: Path) -> None:
    provider = FakeProvider()
    provider.default_model = "provider-default"

    loop = _new_loop(tmp_path, provider=provider, model=None)

    assert loop.model == "provider-default"
    assert provider.default_model_calls == 1


def test_constructor_explicit_model_override(tmp_path: Path) -> None:
    provider = FakeProvider()

    loop = _new_loop(tmp_path, provider=provider, model="explicit-model")

    assert loop.model == "explicit-model"
    assert provider.default_model_calls == 0


def test_optional_exec_config_default(tmp_path: Path) -> None:
    loop = _new_loop(tmp_path, exec_config=None)

    assert isinstance(loop.exec_config, ExecToolConfig)
    assert loop.exec_config.timeout == 60


def test_optional_session_manager_default(tmp_path: Path) -> None:
    loop = _new_loop(tmp_path, session_manager=None)

    assert isinstance(loop.sessions, SessionManager)


def test_optional_session_manager_injected(tmp_path: Path) -> None:
    fake_sessions = FakeSessionManager()

    loop = _new_loop(tmp_path, session_manager=fake_sessions)

    assert loop.sessions is fake_sessions


def test_cron_service_none_no_cron_tool(tmp_path: Path) -> None:
    loop = _new_loop(tmp_path, cron_service=None)

    assert loop.tools.get("cron") is None
    assert "cron" not in loop.tools.tool_names


def test_cron_service_injected_cron_tool_registered(tmp_path: Path) -> None:
    loop = _new_loop(tmp_path, cron_service=Mock())

    assert isinstance(loop.tools.get("cron"), CronTool)


def test_restrict_to_workspace_propagation(tmp_path: Path) -> None:
    loop = _new_loop(tmp_path, restrict_to_workspace=True)

    for name in ["read_file", "write_file", "edit_file", "list_dir"]:
        tool = loop.tools.get(name)
        assert isinstance(tool, (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool))
        assert tool._allowed_dir == tmp_path

    exec_tool = loop.tools.get("exec")
    assert isinstance(exec_tool, ExecTool)
    assert exec_tool.working_dir is not None
    assert exec_tool.restrict_to_workspace is True
    assert Path(exec_tool.working_dir) == tmp_path


def test_brave_api_key_to_web_search_tool(tmp_path: Path) -> None:
    loop = _new_loop(tmp_path, brave_api_key="brave-key")

    web_search = loop.tools.get("web_search")
    assert isinstance(web_search, WebSearchTool)
    assert web_search.api_key == "brave-key"


def test_bus_in_message_tool_callback(tmp_path: Path) -> None:
    bus = MessageBus()
    loop = AgentLoop(bus=bus, provider=FakeProvider(), workspace=tmp_path)

    message_tool = loop.tools.get("message")
    assert isinstance(message_tool, MessageTool)
    assert message_tool._send_callback == bus.publish_outbound


@pytest.mark.asyncio
async def test_process_message_uses_injected_provider(tmp_path: Path, monkeypatch) -> None:
    provider = FakeProvider(
        responses=[
            LLMResponse(
                content="calling tool",
                tool_calls=[
                    ToolCallRequest(id="tool-1", name="read_file", arguments={"path": "README.md"})
                ],
            ),
            LLMResponse(content="final response"),
        ]
    )
    sessions = FakeSessionManager()
    loop = _new_loop(tmp_path, provider=provider, session_manager=sessions)
    monkeypatch.setattr(
        loop.context,
        "build_messages",
        Mock(return_value=[{"role": "user", "content": "hello"}]),
    )
    execute_mock = AsyncMock(return_value="tool-result")
    monkeypatch.setattr(loop.tools, "execute", execute_mock)

    msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
    response = await loop._process_message(msg)

    assert response is not None
    assert response.content == "final response"
    assert len(provider.chat_calls) == 2
    assert provider.chat_calls[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert provider.chat_calls[0]["tools"] == loop.tools.get_definitions()
    assert provider.chat_calls[0]["model"] == loop.model
    execute_mock.assert_awaited_once_with("read_file", {"path": "README.md"})


@pytest.mark.asyncio
async def test_process_message_saves_via_session_manager(tmp_path: Path) -> None:
    sessions = FakeSessionManager()
    loop = _new_loop(
        tmp_path,
        provider=FakeProvider(responses=[LLMResponse(content="assistant says hi")]),
        session_manager=sessions,
    )

    msg = InboundMessage(channel="discord", sender_id="user-1", chat_id="room-7", content="hello")
    await loop._process_message(msg)

    assert len(sessions.saved) == 1
    saved_session = sessions.saved[0]
    assert saved_session.key == "discord:room-7"
    assert [{"role": m["role"], "content": m["content"]} for m in saved_session.messages] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "assistant says hi"},
    ]


@pytest.mark.asyncio
async def test_process_system_message_parses_origin(tmp_path: Path, monkeypatch) -> None:
    sessions = FakeSessionManager()
    loop = _new_loop(
        tmp_path,
        provider=FakeProvider(responses=[LLMResponse(content="done")]),
        session_manager=sessions,
    )
    build_messages_mock = Mock(return_value=[{"role": "user", "content": "announce"}])
    monkeypatch.setattr(loop.context, "build_messages", build_messages_mock)

    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="slack:C123",
        content="subagent result",
    )
    response = await loop._process_system_message(msg)

    assert response is not None
    assert response.channel == "slack"
    assert response.chat_id == "C123"
    assert sessions.requested_keys[-1] == "slack:C123"
    build_messages_mock.assert_called_once()
    assert build_messages_mock.call_args.kwargs["channel"] == "slack"
    assert build_messages_mock.call_args.kwargs["chat_id"] == "C123"

    message_tool = loop.tools.get("message")
    assert isinstance(message_tool, MessageTool)
    assert message_tool._default_channel == "slack"
    assert message_tool._default_chat_id == "C123"


@pytest.mark.asyncio
async def test_run_error_publishes_fallback_via_bus(tmp_path: Path, monkeypatch) -> None:
    msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
    bus = MessageBus()
    consume_mock = AsyncMock(return_value=msg)
    publish_mock = AsyncMock()
    monkeypatch.setattr(bus, "consume_inbound", consume_mock)
    monkeypatch.setattr(bus, "publish_outbound", publish_mock)

    loop = AgentLoop(bus=bus, provider=FakeProvider(), workspace=tmp_path)

    async def _boom(_msg: InboundMessage) -> OutboundMessage | None:
        loop.stop()
        raise RuntimeError("failure")

    process_mock = AsyncMock(side_effect=_boom)
    monkeypatch.setattr(loop, "_process_message", process_mock)

    await loop.run()

    publish_mock.assert_awaited_once()
    assert publish_mock.await_args is not None
    published = publish_mock.await_args.args[0]
    assert isinstance(published, OutboundMessage)
    assert published.channel == "telegram"
    assert published.chat_id == "c1"
    assert published.content == "Sorry, I encountered an error: failure"


@pytest.mark.asyncio
async def test_process_direct_delegation(tmp_path: Path, monkeypatch) -> None:
    loop = _new_loop(tmp_path)
    process_mock = AsyncMock(
        return_value=OutboundMessage(channel="cli", chat_id="direct", content="direct output")
    )
    monkeypatch.setattr(loop, "_process_message", process_mock)

    result = await loop.process_direct(content="hello", channel="cli", chat_id="abc")

    assert result == "direct output"
    process_mock.assert_awaited_once()
    assert process_mock.await_args is not None
    wrapped = process_mock.await_args.args[0]
    assert isinstance(wrapped, InboundMessage)
    assert wrapped.channel == "cli"
    assert wrapped.sender_id == "user"
    assert wrapped.chat_id == "abc"
    assert wrapped.content == "hello"
