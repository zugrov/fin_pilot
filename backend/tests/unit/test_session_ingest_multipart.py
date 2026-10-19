import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.config import Settings
from app.errors import AppError
from app.services import session_ingest_multipart as multipart_mod
from app.services.session_ingest_multipart import close_upload_files, parse_session_ingest_multipart
from starlette.requests import Request


def _multipart_bytes(boundary: str, parts: list[tuple[str, str | None, bytes]]) -> bytes:
    chunks: list[bytes] = []
    for name, filename, content in parts:
        chunks.append(f"--{boundary}\r\n".encode())
        if filename is None:
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        else:
            chunks.append(
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    "Content-Type: application/octet-stream\r\n\r\n"
                ).encode()
            )
        chunks.append(content)
        if not content.endswith(b"\r\n"):
            chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks)


def _request_for_body(body: bytes, boundary: str) -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/",
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
        ],
    }
    return Request(scope, receive)


def _settings(**overrides) -> Settings:
    base = Settings()
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_close_upload_files_closes_every_upload() -> None:
    first = MagicMock()
    first.close = AsyncMock()
    second = MagicMock()
    second.close = AsyncMock()
    asyncio.run(close_upload_files([first, second]))
    first.close.assert_awaited_once()
    second.close.assert_awaited_once()


def test_duplicate_envelope_closes_unread_uploads() -> None:
    boundary = "----finpilot-unit-boundary"
    env = '{"schema_version":"1.0-session"}'
    body = _multipart_bytes(
        boundary,
        [
            ("envelope", None, env.encode()),
            ("envelope", None, env.encode()),
            ("files", "a.csv", b"data-a"),
            ("files", "b.csv", b"data-b"),
        ],
    )
    request = _request_for_body(body, boundary)
    settings = _settings()
    close_calls: list[int] = []
    original = multipart_mod.close_upload_files

    async def track_close(uploads):
        close_calls.append(len(list(uploads)))
        await original(uploads)

    with patch.object(multipart_mod, "close_upload_files", side_effect=track_close):
        with pytest.raises(AppError) as exc:
            asyncio.run(parse_session_ingest_multipart(request, settings))
    assert exc.value.status_code == 422
    assert close_calls == [2]


def test_oversized_first_file_closes_remaining_uploads() -> None:
    boundary = "----finpilot-oversize-boundary"
    env = '{"schema_version":"1.0-session"}'
    big = b"x" * 64
    small = b"y" * 8
    body = _multipart_bytes(
        boundary,
        [
            ("envelope", None, env.encode()),
            ("files", "big.csv", big),
            ("files", "small.csv", small),
        ],
    )
    request = _request_for_body(body, boundary)
    settings = _settings(import_max_bytes=32)
    close_calls: list[int] = []
    original = multipart_mod.close_upload_files

    async def track_close(uploads):
        close_calls.append(len(list(uploads)))
        await original(uploads)

    with patch.object(multipart_mod, "close_upload_files", side_effect=track_close):
        with pytest.raises(AppError) as exc:
            asyncio.run(parse_session_ingest_multipart(request, settings))
    assert exc.value.status_code == 413
    assert close_calls == [2]


def test_raw_body_overflow_during_parse() -> None:
    boundary = "----finpilot-overflow-boundary"
    env = '{"schema_version":"1.0-session"}'
    body = _multipart_bytes(
        boundary,
        [
            ("envelope", None, env.encode()),
            ("files", "p.csv", b"x" * 512),
        ],
    )
    request = _request_for_body(body, boundary)
    settings = _settings(session_ingest_max_body_bytes=128)
    with pytest.raises(AppError) as exc:
        asyncio.run(parse_session_ingest_multipart(request, settings))
    assert exc.value.status_code == 413


def test_malformed_multipart_returns_422() -> None:
    boundary = "----finpilot-bad-boundary"
    body = b"--" + boundary.encode() + b"\r\nincomplete"
    request = _request_for_body(body, boundary)
    settings = _settings()
    with pytest.raises(AppError) as exc:
        asyncio.run(parse_session_ingest_multipart(request, settings))
    assert exc.value.status_code == 422
