"""Ограничение raw multipart body для session ingest (FA-R02.3)."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from app.config import Settings
from app.errors import AppError
from fastapi import Request
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser


async def _bounded_stream(request: Request, max_bytes: int) -> AsyncGenerator[bytes, None]:
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise AppError(413, "payload_too_large", "Превышен лимит тела запроса")
        yield chunk


async def parse_session_ingest_multipart(
    request: Request, settings: Settings
) -> tuple[str, list[bytes]]:
    content_type = request.headers.get("content-type") or ""
    if "multipart/form-data" not in content_type.lower():
        raise AppError(422, "validation_error", "Ожидается multipart/form-data")

    max_part = max(settings.session_ingest_max_envelope_bytes, settings.import_max_bytes)
    parser = MultiPartParser(
        request.headers,
        _bounded_stream(request, settings.session_ingest_max_body_bytes),
        max_files=settings.session_ingest_max_parts,
        max_fields=settings.session_ingest_max_parts + 2,
        max_part_size=max_part,
    )
    try:
        form = await parser.parse()
    except MultiPartException as exc:
        raise AppError(422, "validation_error", exc.message) from exc

    envelope: str | None = None
    files: list[bytes] = []
    for name, value in form.multi_items():
        if name == "envelope":
            if not isinstance(value, str):
                raise AppError(422, "validation_error", "Поле envelope должно быть текстом")
            envelope = value
        elif name == "files":
            if not isinstance(value, UploadFile):
                raise AppError(422, "validation_error", "files должны быть файлами")
            upload = value
            try:
                limit = settings.import_max_bytes + 1
                data = await upload.read(limit)
            finally:
                await upload.close()
            if len(data) > settings.import_max_bytes:
                raise AppError(413, "payload_too_large", "Файл больше лимита")
            files.append(data)
        else:
            raise AppError(422, "validation_error", f"Неизвестное поле multipart: {name}")

    if envelope is None:
        raise AppError(422, "validation_error", "Нужно поле envelope")
    if not files:
        raise AppError(422, "validation_error", "Нужен хотя бы один файл")
    if len(files) > settings.session_ingest_max_parts:
        raise AppError(422, "validation_error", "Слишком много файлов")
    return envelope, files
