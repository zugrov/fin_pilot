# FA-R03.2 · парсеры и сверка 1С БП 3.0 (plan)

**Статус:** plan-first (2026-10-27). **Реальные данные клиента** — только `var/fa-r03-client-samples/` (gitignored).

## Порядок пакетов

| Пакет | Содержание | Статус |
|-------|------------|--------|
| **FA-R03.2a** | Исправление `read_clientbank` (направление, `external_id`, cp1251) | **done in repo** |
| **FA-R03.2b** | Сверка S1/S2/S3 как **чистые функции** над уже распарсенными списками | planned |
| **FA-R03.2c** | Тонкий слой чтения `.xls` → списки строк/ячеек | planned |

## FA-R03.2a (принято)

- Модуль: [`backend/app/domain/imports/clientbank.py`](../../backend/app/domain/imports/clientbank.py).
- Направление: непустая `ДатаСписано` / `ДатаПоступило`; при обеих пустых или обеих непустых — по `РасчСчет` секции vs `Плательщик*` / `Получатель*`; конфликт → `direction_conflict`.
- `external_id`: `cb-{sha256…}` из счёта, номера, даты, направления, суммы, ИНН, hash назначения; полные дубликаты → суффикс `~n` и `possible_duplicate` в `raw`.
- **Re-import:** **решение владельца 2026-10-27** — срез 2a **без** миграции identity (реальные ClientBank не коммитились). Повторная загрузка старых batch с `external_id=Номер` по-прежнему создаст **новые** identity относительно `cb-…`.
- Тесты: [`backend/tests/unit/test_clientbank_export_profile.py`](../../backend/tests/unit/test_clientbank_export_profile.py), фикстура `clientbank_export_profile.cp1251.txt` (синтетика, cp1251).

## FA-R03.2b · сверка (без .xls)

Чистые функции (новый модуль, рабочее имя `backend/app/domain/imports/fa_r03/reconcile.py`):

- Формула остатка: `opening + in − out = closing` (Decimal).
- Цепочка суток: `closing(N) = opening(N+1)`.
- Итоги S1 = S2 = S3 по счёту **51** (допуск **0,00**).
- S1 ↔ S2: ключ `direction + business_date + amount + document_number`; учёт **1→N** строк карточки (14 кейсов в локальном протоколе).

Вход: typed rows из парсера S1 и row-списки из 2c (не файлы).

Юнит-тесты только на **синтетических** списках (минимальные dict/Decimal), без клиентских сумм в git.

## FA-R03.2c · чтение .xls

- **xlrd 2.0.1** — только **dev-dependency** (optional group); **принято владельцем 2026-10-27**; в CI/prod **не устанавливать** до отдельного процесса.
- **Бинарных .xls-фикстур в репозитории нет.** Покрытие: ручной тест с маркером `@pytest.mark.manual` (локальный путь к S2/S3 в `var/…`); юнит-тесты сверки — на списках после stub-парсера в тесте.
- Суммы из ячеек: `Decimal(str(v))`, нормализация **не более 2** знаков (`money()`).
- Модули (план): `backend/app/domain/imports/fa_r03/card51_xls.py`, `osv_xls.py` — только преобразование лист → `list[list[str]]` / row dicts.

## Связь с ingestion

- S1 → существующий pipeline `detect_format` → `read_clientbank` → `import_service` / `ClassificationRule` (ClientBank без `category_code`).
- S2/S3 **не** пишут в ledger в v1; CLI или pytest reconcile против S1.
- **FA-R03.3 (идея):** корреспондирующие счета из карточки (62/60/70/55.03/50.01) как **классификатор** cash/revenue — не в scope 2b/2c.

## Риски (из образца S1–S3)

- **55.03**, **наличные** — не операционный ClientBank.
- Возврат покупателю через **91.02** в карточке.
- Разбиение одного платежа на несколько строк S2.
- Контрагент **без ИНН** в карточке.
- Дубликаты номеров платёжек в S1 (решено составным `external_id`).

## Файлы (ожидаемые)

| Файл | Пакет |
|------|-------|
| `app/domain/imports/clientbank.py` | 2a ✓ |
| `tests/unit/test_clientbank_export_profile.py` | 2a ✓ |
| `app/domain/imports/fa_r03/reconcile.py` | 2b |
| `tests/unit/test_fa_r03_reconcile.py` | 2b |
| `app/domain/imports/fa_r03/card51_xls.py`, `osv_xls.py` | 2c |
| `tests/unit/test_fa_r03_xls_manual.py` (manual mark) | 2c |
