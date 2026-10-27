"""Загрузка каталогов classification pack из файловой системы."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.errors import AppError

PACKS_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class PackRuleSpec:
    key: str
    local_priority: int
    category_code: str
    title: str
    conditions: dict[str, Any]


@dataclass(frozen=True)
class ClassificationPack:
    slug: str
    version: str
    priority_base: int
    display_name: str
    rules: tuple[PackRuleSpec, ...]

    def rule_name(self, spec: PackRuleSpec) -> str:
        return f"[pack:{self.slug}@{self.version}] {spec.title}"


def rule_priority(pack: ClassificationPack, spec: PackRuleSpec) -> int:
    return pack.priority_base + spec.local_priority


def _pack_dir(slug: str, version: str) -> Path:
    path = PACKS_ROOT / slug / version
    if not path.is_dir():
        raise AppError(404, "not_found", "Набор правил не найден")
    return path


def load_pack(slug: str, version: str) -> ClassificationPack:
    base = _pack_dir(slug, version)
    meta_path = base / "pack.json"
    rules_path = base / "rules.json"
    if not meta_path.is_file() or not rules_path.is_file():
        raise AppError(404, "not_found", "Набор правил не найден")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    rules_doc = json.loads(rules_path.read_text(encoding="utf-8"))
    if meta.get("slug") != slug or str(meta.get("version")) != version:
        raise AppError(422, "validation_error", "Метаданные набора не совпадают с путём")
    priority_base = int(meta.get("priority_base", 1000))
    specs: list[PackRuleSpec] = []
    for raw in rules_doc.get("rules") or []:
        key = str(raw["key"])
        specs.append(
            PackRuleSpec(
                key=key,
                local_priority=int(raw["local_priority"]),
                category_code=str(raw["category_code"]),
                title=str(raw["title"]),
                conditions=dict(raw["conditions"]),
            )
        )
    if not specs:
        raise AppError(422, "validation_error", "Набор не содержит правил")
    return ClassificationPack(
        slug=slug,
        version=version,
        priority_base=priority_base,
        display_name=str(meta.get("display_name") or slug),
        rules=tuple(specs),
    )


def list_pack_versions(slug: str) -> tuple[str, ...]:
    root = PACKS_ROOT / slug
    if not root.is_dir():
        return ()
    return tuple(sorted(p.name for p in root.iterdir() if p.is_dir()))
