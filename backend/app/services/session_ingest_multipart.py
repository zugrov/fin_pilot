"""Ограничение raw multipart body для session ingest (FA-R02.3)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable

from app.config import Settings
from app.errors import AppError
from fastapi import Request
from starlette.datastructures import FormData, UploadFile
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


def uploads_in_form(form: FormData) -> list[UploadFile]:
    return [value for _, value in form.multi_items() if isinstance(value, UploadFile)]


async def close_upload_files(uploads: Iterable[UploadFile]) -> None:
    for upload in uploads:
        try:
            await upload.close()
        except Exception:
            continue


async def _parse_multipart_form(
    request: Request, settings: Settings
) -> tuple[MultiPartParser, FormData]:
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
        for handle in parser._files_to_close_on_error:  # noqa: SLF001
            try:
                handle.close()
            except Exception:
                pass
        raise AppError(422, "validation_error", exc.message) from exc
    except AppError:
        for handle in parser._files_to_close_on_error:  # noqa: SLF001
            try:
                handle.close()
            except Exception:
                pass
        raise
    except BaseException:
        for handle in parser._files_to_close_on_error:  # noqa: SLF001
            try:
                handle.close()
            except Exception:
                pass
        raise
    return parser, form


async def parse_session_ingest_multipart(
    request: Request, settings: Settings
) -> tuple[str, list[bytes]]:
    _parser, form = await _parse_multipart_form(request, settings)
    pending = uploads_in_form(form)
    try:
        envelope: str | None = None
        files: list[bytes] = []
        for name, value in form.multi_items():
            if name == "envelope":
                if not isinstance(value, str):
                    raise AppError(422, "validation_error", "Поле envelope должно быть текстом")
                if envelope is not None:
                    raise AppError(422, "validation_error", "Поле envelope должно быть одно")
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
    finally:
        await close_upload_files(pending)
