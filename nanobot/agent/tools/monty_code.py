import asyncio
import importlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.utils.helpers import ensure_dir, get_data_path


class MontyCodeTool(Tool):
    def __init__(
        self,
        timeout: int = 10,
        uv_python: str = "3.12",
    ):
        self.timeout = timeout
        self.uv_python = uv_python
        self.run_root = ensure_dir(get_data_path() / "code-runs")

    @property
    def name(self) -> str:
        return "code"

    @property
    def description(self) -> str:
        return (
            "Execute pure-logic Python code in a Monty sandbox. "
            "Use this when no external dependency installation is needed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute in Monty sandbox",
                    "minLength": 1,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Execution timeout in seconds",
                    "minimum": 1,
                    "maximum": 120,
                },
                "mode": {
                    "type": "string",
                    "description": "Execution mode: auto selects monty unless dependencies are provided",
                    "enum": ["auto", "monty", "uv"],
                },
                "dependencies": {
                    "type": "array",
                    "description": "Python dependencies for uv execution mode",
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "required": ["code"],
        }

    async def execute(self, **kwargs: Any) -> str:
        code = kwargs.get("code", "")
        timeout = kwargs.get("timeout")
        mode = kwargs.get("mode", "auto")
        dependencies = kwargs.get("dependencies") or []

        if not code.strip():
            return "Error: code must not be empty"

        if mode not in {"auto", "monty", "uv"}:
            return "Error: mode must be one of auto, monty, uv"

        if not isinstance(dependencies, list) or not all(
            isinstance(dep, str) and dep.strip() for dep in dependencies
        ):
            return "Error: dependencies must be an array of non-empty strings"

        use_uv = mode == "uv" or (mode == "auto" and len(dependencies) > 0)

        if use_uv:
            return await self._execute_with_uv(
                code=code, timeout=timeout, dependencies=dependencies
            )

        return await self._execute_with_monty(code=code, timeout=timeout)

    async def _execute_with_monty(self, code: str, timeout: Any) -> str:
        try:
            pydantic_monty = importlib.import_module("pydantic_monty")
        except ImportError:
            return "Error: pydantic-monty is not installed"

        effective_timeout = timeout if isinstance(timeout, int) and timeout > 0 else self.timeout

        try:
            monty = pydantic_monty.Monty(code, inputs=[])
            try:
                result = await asyncio.wait_for(
                    pydantic_monty.run_monty_async(monty),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                return f"Error: Monty sandbox timed out after {effective_timeout} seconds"

            if result is None:
                return "(no output)"

            return self._truncate(str(result))
        except Exception as e:
            return f"Error executing Monty sandbox: {str(e)}"

    async def _execute_with_uv(self, code: str, timeout: Any, dependencies: list[str]) -> str:
        effective_timeout = timeout if isinstance(timeout, int) and timeout > 0 else self.timeout

        if shutil.which("uv") is None:
            return "Error: uv is not installed"

        try:
            with tempfile.TemporaryDirectory(prefix="run-", dir=str(self.run_root)) as temp_dir:
                script_path = Path(temp_dir) / "script.py"
                script_path.write_text(code, encoding="utf-8")

                command = [
                    "uv",
                    "run",
                    "--no-project",
                    "--isolated",
                    "--no-cache",
                    "--python",
                    self.uv_python,
                ]
                for dep in dependencies:
                    command.extend(["--with", dep])
                command.append(str(script_path))

                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=temp_dir,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=effective_timeout,
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    return f"Error: uv execution timed out after {effective_timeout} seconds"

                output_parts = []
                if stdout:
                    output_parts.append(stdout.decode("utf-8", errors="replace"))

                if stderr:
                    stderr_text = stderr.decode("utf-8", errors="replace").strip()
                    if stderr_text:
                        output_parts.append(f"STDERR:\n{stderr_text}")

                if process.returncode != 0:
                    output_parts.append(f"\nExit code: {process.returncode}")

                result = "\n".join(output_parts) if output_parts else "(no output)"
                return self._truncate(result)
        except Exception as e:
            return f"Error executing uv environment: {str(e)}"

    def _truncate(self, value: str) -> str:
        max_len = 10000
        if len(value) > max_len:
            return value[:max_len] + f"\n... (truncated, {len(value) - max_len} more chars)"
        return value
