from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from http import HTTPStatus
from typing import Optional
from urllib.parse import urlsplit

from loguru import logger

from nanobot.config.schema import A2AConfig

from .router import A2ARouter, RouteResult


@dataclass(slots=True)
class HTTPRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


class HTTPParseError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class A2AServer:
    def __init__(self, config: A2AConfig):
        self.config = config
        self.router = A2ARouter(config)
        self._server: Optional[asyncio.Server] = None
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        if not self.config.enabled:
            return
        if self._server is not None:
            return

        self._shutdown.clear()
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self.config.host,
            port=self.config.port,
        )
        logger.info(f"A2A server listening on http://{self.config.host}:{self.config.port}")

    async def run(self) -> None:
        if self._server is None:
            return
        await self._shutdown.wait()

    def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        self._shutdown.set()

    async def wait_closed(self) -> None:
        if self._server is None:
            return
        await self._server.wait_closed()
        self._server = None
        logger.info("A2A server stopped")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = await asyncio.wait_for(
                self._read_request(reader), timeout=self.config.request_timeout
            )
            result = self.router.handle(
                method=request.method,
                path=request.path,
                headers=request.headers,
                body=request.body,
            )
            await self._write_json_response(writer, result)
        except HTTPParseError as exc:
            payload = {"error": {"code": exc.code, "message": exc.message, "details": {}}}
            await self._write_json_response(
                writer, RouteResult(status_code=exc.status_code, payload=payload)
            )
        except asyncio.TimeoutError:
            payload = {
                "error": {
                    "code": "request_timeout",
                    "message": "Request processing timed out",
                    "details": {},
                }
            }
            await self._write_json_response(writer, RouteResult(status_code=408, payload=payload))
        except Exception as exc:
            logger.exception(f"Unhandled A2A server error: {exc}")
            payload = {
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error",
                    "details": {},
                }
            }
            await self._write_json_response(writer, RouteResult(status_code=500, payload=payload))
        finally:
            writer.close()
            await writer.wait_closed()

    async def _read_request(self, reader: asyncio.StreamReader) -> HTTPRequest:
        request_line_raw = await reader.readline()
        if not request_line_raw:
            raise HTTPParseError(status_code=400, code="invalid_request", message="Empty request")

        try:
            request_line = request_line_raw.decode("ascii").strip()
            method, raw_target, _ = request_line.split(" ", 2)
        except ValueError as exc:
            raise HTTPParseError(
                status_code=400, code="invalid_request", message="Malformed request line"
            ) from exc

        headers: dict[str, str] = {}
        while True:
            header_line_raw = await reader.readline()
            if header_line_raw in (b"\r\n", b"\n", b""):
                break
            try:
                header_line = header_line_raw.decode("ascii")
            except UnicodeDecodeError as exc:
                raise HTTPParseError(
                    status_code=400, code="invalid_request", message="Invalid request header"
                ) from exc

            if ":" not in header_line:
                raise HTTPParseError(
                    status_code=400, code="invalid_request", message="Malformed header line"
                )

            key, value = header_line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        content_length = 0
        if "content-length" in headers:
            try:
                content_length = int(headers["content-length"])
            except ValueError as exc:
                raise HTTPParseError(
                    status_code=400, code="invalid_request", message="Invalid content-length"
                ) from exc

        if content_length < 0:
            raise HTTPParseError(
                status_code=400, code="invalid_request", message="Negative content-length"
            )

        if content_length > self.config.max_request_size:
            raise HTTPParseError(
                status_code=413, code="payload_too_large", message="Request body exceeds limit"
            )

        try:
            body = await reader.readexactly(content_length) if content_length else b""
        except asyncio.IncompleteReadError as exc:
            raise HTTPParseError(
                status_code=400, code="invalid_request", message="Incomplete request body"
            ) from exc

        path = urlsplit(raw_target).path or "/"
        return HTTPRequest(method=method.upper(), path=path, headers=headers, body=body)

    async def _write_json_response(self, writer: asyncio.StreamWriter, result: RouteResult) -> None:
        reason = HTTPStatus(result.status_code).phrase
        body = json.dumps(result.payload).encode("utf-8")
        headers = [
            f"HTTP/1.1 {result.status_code} {reason}",
            "Content-Type: application/json; charset=utf-8",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        ]
        writer.write("\r\n".join(headers).encode("ascii") + body)
        await writer.drain()
