# FA-R00.4 · Контракты и очередь (локальная подготовка)

Статус задачи: **local_verified** (принято 2026-10-17). Этап FA-R00 и G0 приняты.

## Артефакты

| Файл | Назначение |
| --- | --- |
| `contracts/delivery-contract.md` | общий контракт доставки |
| `contracts/state-machines.md` | состояния transport / parse / financial / completeness |
| `contracts/ingestion-delivery.schema.json` | JSON Schema оболочки + record defs |
| `contracts/examples/*.json` | cash, revenue, plan |
| `contracts/ingestion-proposed.openapi.yaml` | proposed маршруты |
| `contracts/test-vectors-ingestion.md` | 11 сценариев |
| `contracts/validate_contracts.py` | `--mode full` или `structural-only` |
| `contracts/validation-tools.lock.txt` | зафиксированные версии pip (внешний venv) |
| `contracts/examples/negative/*.json` | отрицательные контрактные примеры |
| `contracts/fixtures/schema-unresolvable-ref.json` | тест неразрешимого `$ref` |
| `STAGE_FA-R01.md` | пакет R01.1 и зависимости R01 |
| `STAGE_FA-R02-bootstrap.md` | R02.1–R02.4 bootstrap |

## Матрица capabilities (профиль D2, услуги)

| dataset | D3 near scope | Schema example | As-is import |
| --- | --- | --- | --- |
| cash | да | delivery-cash | csv, xlsx, clientbank |
| revenue | да | delivery-revenue | csv |
| plan | да | delivery-plan | planned_cash.csv |
| budget | расширение | enum only | csv |
| OCR/docs | нет | — | — |

## Проверка контрактов (воспроизведение)

Виртуальное окружение **вне репозитория** (не меняет pyproject/uv/package.json приложения):

```bash
VENV="$HOME/.local/venvs/finpilot-contracts-20261017"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -r docs/roadmap/contracts/validation-tools.lock.txt
"$VENV/bin/python" docs/roadmap/contracts/validate_contracts.py --mode full
```

Ключевые версии (полный список — `validation-tools.lock.txt`):

| Пакет | Версия |
| --- | --- |
| jsonschema | 4.23.0 |
| openapi-spec-validator | 0.7.1 |
| PyYAML | 6.0.2 |

Без установленных пакетов `--mode full` завершится кодом **2** (`INCOMPLETE`).
Режим `--mode structural-only` не заменяет полную проверку.

**Python 3.9** в инструкции относится только к **отдельному venv** проверки контрактов.
Runtime приложения и CI: **Python 3.12** (`backend/pyproject`, workflow `ci.yml`).

### Full validation (факт)

Полная проверка **выполнена локально** перед коммитом архитектурного пакета:
`validate_contracts.py --mode full` → `RESULT full failures=0`, exit 0.

### CI репозитория (на момент пакета)

| Проверка | В CI (`/.github/workflows/ci.yml`) | Контракты roadmap |
| --- | --- | --- |
| Ruff, mypy, pytest (Postgres 16) | да | нет |
| Frontend vitest + build | да | нет |
| JSON Schema / OpenAPI контрактов | **нет** | локально `--mode full` |
| `validate_contracts.py` | **нет** | вручную / venv по lock |

Добавление контрактной проверки в CI — отдельное решение (не входит в G0).

Проверки **не** покрывают: дедупликацию между каналами, права, транзакции,
порядок ревизий, unpost, продвижение полноты — см. `test-vectors-ingestion.md`.

Схемы и OpenAPI **не** отправлялись в онлайн-валидаторы; `$ref` только локальные `#/…`.

## G0 (FA-R00 целиком) — принято 2026-10-17

- [x] FA-R00.1 inventory
- [x] FA-R00.2 decisions
- [x] FA-R00.3 ADR direction (вариант B)
- [x] FA-R00.4 контракты и очередь + full validation
- [x] G0: архитектурное решение и очередь R01 согласованы
