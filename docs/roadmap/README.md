# Roadmap vNext 3.0 — индекс материалов

Единый источник состояния: `STATE.json`.
Архитектурный этап **FA-R00** и **G0** приняты 2026-10-17 (коммит архитектурного пакета).

## План и состояние

| Файл | Назначение |
| --- | --- |
| [MASTER_PLAN.md](MASTER_PLAN.md) | Согласованный план разработки vNext 3.0 |
| [STATE.json](STATE.json) | Текущий этап, задачи, 16 этапов FA-R00…R15, SHA |
| [DECISIONS.md](DECISIONS.md) | Решения владельца и журнал приёмки |

## FA-R00 (принят)

| Файл | Назначение |
| --- | --- |
| [FA-R00.1-inventory.md](FA-R00.1-inventory.md) | Инвентаризация as-is |
| [ADR-001-unified-ingestion.md](ADR-001-unified-ingestion.md) | ADR: IngestionDelivery + ImportBatch |
| [FA-R00.4-contracts.md](FA-R00.4-contracts.md) | Контракты, валидация, G0 |

## Контракты (проект, не runtime)

| Путь | Назначение |
| --- | --- |
| [contracts/delivery-contract.md](contracts/delivery-contract.md) | Контракт доставки |
| [contracts/state-machines.md](contracts/state-machines.md) | Состояния transport/parse/financial/completeness |
| [contracts/ingestion-delivery.schema.json](contracts/ingestion-delivery.schema.json) | JSON Schema оболочки |
| [contracts/ingestion-proposed.openapi.yaml](contracts/ingestion-proposed.openapi.yaml) | Proposed OpenAPI (маршрутов в приложении нет) |
| [contracts/test-vectors-ingestion.md](contracts/test-vectors-ingestion.md) | 11 сценариев + backlog интеграции |
| [contracts/validate_contracts.py](contracts/validate_contracts.py) | `--mode full` / `structural-only` |
| [contracts/validation-tools.lock.txt](contracts/validation-tools.lock.txt) | Версии pip для **отдельного** venv |
| [contracts/examples/](contracts/examples/) | Положительные примеры |
| [contracts/examples/negative/](contracts/examples/negative/) | Негативные примеры |
| [contracts/fixtures/](contracts/fixtures/) | Тестовая схема с битым `$ref` |

## Следующие этапы (очередь, не разрешение на код)

| Файл | Назначение |
| --- | --- |
| [STAGE_FA-R01.md](STAGE_FA-R01.md) | Пакет FA-R01.1 и зависимости |
| [STAGE_FA-R02-bootstrap.md](STAGE_FA-R02-bootstrap.md) | Первые задачи FA-R02 |

Текущая задача по STATE: **FA-R01.1** (статус `ready`, код — только после отдельного разрешения).
