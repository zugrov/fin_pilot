# FA-R06.2 · Соответствие ТЗ v2.0 §10 «Классификация»

**Источник:** [financial_autopilot_complete_spec_v2_0.md](../../financial_autopilot_complete_spec_v2_0.md), §10.  
**Срез продукта (baseline):** `db58f0f3ce37dd55901a51534b887d22b6af7ffe` (+ локальные правки FA-R06.2-B2 без отдельного commit на момент составления).  
**Статус документа:** матрица трассировки «требование → as-is → тест»; не заменяет приёмку этапа.

Легенда: **есть** — поведение покрыто кодом и тестом; **частично** — есть подмножество или без полного UX/API; **нет** — не реализовано или явно вне текущего scope.

---

## Сводная таблица

| ID | Требование (§10 ТЗ v2.0) | Статус | As-is / пробел | Тест / доказательство |
|----|--------------------------|--------|----------------|------------------------|
| **C1** | Условие: **ИНН контрагента** | **есть** | `counterparty_inn` в `CONDITION_KEYS`, матч в `matching_category` | [`backend/tests/integration/test_classification_screen_api.py`](../../backend/tests/integration/test_classification_screen_api.py) (`test_create_rule_*`, retail polygon); [`frontend/src/lib/classificationForm.test.ts`](../../frontend/src/lib/classificationForm.test.ts) |
| **C2** | Условие: **текст назначения contains** | **есть** | `description_contains`, case-insensitive | [`backend/tests/synthetic_polygon/classification_harness.py`](../../backend/tests/synthetic_polygon/classification_harness.py) `RETAIL_CLIENTBANK_IN_RULE`; [`backend/tests/integration/test_cashflow_classification_polygon.py`](../../backend/tests/integration/test_cashflow_classification_polygon.py); [`frontend/e2e/classification-polygon.spec.ts`](../../frontend/e2e/classification-polygon.spec.ts) |
| **C3** | Условие: **текст назначения equals** | **нет** | Только «содержит», не полное совпадение | — |
| **C4** | Условие: **направление** (in/out) | **есть** | `direction` в условиях | те же polygon / harness |
| **C5** | Условие: **диапазон суммы** | **есть** | `amount_min` / `amount_max`, Decimal | [`frontend/src/lib/classificationForm.test.ts`](../../frontend/src/lib/classificationForm.test.ts); валидация 422 в API |
| **C6** | Условие: **кошелёк (wallet)** | **нет** | Нет ключа в `CONDITION_KEYS` | — |
| **C7** | Условие: **источник (source)** | **нет** | Нет ключа в `CONDITION_KEYS` | — |
| **C8** | Условие: **regex** | **нет** | В ТЗ — вне beta; в коде не заложено | — |
| **A1** | Действие: **категория** | **есть** | `actions_json.category_code`; import `_prepare` и apply | [`backend/tests/integration/test_cashflow_classification_polygon.py`](../../backend/tests/integration/test_cashflow_classification_polygon.py); [`backend/tests/integration/test_classification_rule_apply.py`](../../backend/tests/integration/test_classification_rule_apply.py) |
| **A2** | Действие: **направление** | **нет** | Правило не меняет `direction` операции | — |
| **A3** | Действие: **флаг связанной стороны** | **нет** | Нет поля в `actions_json` | — |
| **A4** | **Transfer pairing** — отдельное подтверждаемое действие | **нет** | Связка переводов — `POST /api/v1/transfers/link` (FA-R06.1), не action правила | [`backend/tests/synthetic_polygon/cashflow_harness.py`](../../backend/tests/synthetic_polygon/cashflow_harness.py) |
| **P1** | Приоритет: **ручная locked-классификация** выше правил | **есть** | `locked_classification` → skip в preview/apply | [`backend/tests/integration/test_import_api.py`](../../backend/tests/integration/test_import_api.py) `test_i9_locked_classification_survives_import`; [`backend/tests/integration/test_classification_rule_apply.py`](../../backend/tests/integration/test_classification_rule_apply.py) `test_apply_respects_locked_and_existing_category`, `test_apply_does_not_overwrite_manual_classification_race`; ТЗ §22 **I9** |
| **P2** | Приоритет: **правило фирмы (company)** | **есть** | `company_id` при создании; `_rule_views` для фирмы | [`backend/tests/integration/test_classification_screen_api.py`](../../backend/tests/integration/test_classification_screen_api.py) `test_patch_priority_changes_import_winner` |
| **P3** | Приоритет: **правило tenant** (`company_id IS NULL`) | **частично** | Участвует в `matching_category` при чтении; **POST API** создаёт только company-scope; seed SQL — [`insert_tenant_wide_rule`](../../backend/tests/synthetic_polygon/classification_harness.py) без integration-сценария | — |
| **P4** | **First match** по приоритету правил | **есть** | `sorted(..., key=priority)` в `matching_category` | [`backend/tests/integration/test_classification_rule_apply.py`](../../backend/tests/integration/test_classification_rule_apply.py) `test_apply_skips_when_higher_priority_rule_wins` |
| **P5** | **Tie-break** по stable ID + **warning conflict** | **есть** (B3b) | `ORDER BY priority, id`; `matching_rule`; warnings create/preview/apply; import `quality_flags` | [`backend/tests/unit/test_classification_rules_match.py`](../../backend/tests/unit/test_classification_rules_match.py); [`backend/tests/integration/test_classification_rule_apply.py`](../../backend/tests/integration/test_classification_rule_apply.py) `test_import_and_apply_same_winner_on_tie_priority`; [`backend/tests/integration/test_classification_screen_api.py`](../../backend/tests/integration/test_classification_screen_api.py) `test_create_rule_replay_returns_same_warning`; [`frontend/src/lib/classificationEvidence.test.ts`](../../frontend/src/lib/classificationEvidence.test.ts) |
| **P6** | Fallback **unclassified** | **есть** | Без категории → unmapped в ОДДС; очередь unclassified API | [`backend/tests/integration/test_classification_screen_api.py`](../../backend/tests/integration/test_classification_screen_api.py) `test_unclassified_*`; [`backend/tests/integration/test_cashflow_classification_polygon.py`](../../backend/tests/integration/test_cashflow_classification_polygon.py) (unmapped 7200.00) |
| **E1** | **Evidence:** rule / version на операции | **есть** (B3b) | Колонки `classification_rule_id`, `classification_rule_version`; API `classification_evidence`; без JSONB snapshot и backfill; `legacy_unknown` при `origin=rule` без id | [`backend/tests/integration/test_classification_rule_apply.py`](../../backend/tests/integration/test_classification_rule_apply.py) `test_apply_records_classification_evidence`, `test_manual_classify_clears_rule_evidence`; [`backend/tests/integration/test_migration_classification_evidence.py`](../../backend/tests/integration/test_migration_classification_evidence.py); [`backend/tests/integration/test_classification_evidence_rls.py`](../../backend/tests/integration/test_classification_evidence_rls.py); [`frontend/src/lib/classificationEvidence.test.ts`](../../frontend/src/lib/classificationEvidence.test.ts) |
| **E2** | Evidence в **ответе preview** (прозрачность) | **частично** | Preview: tx id, description, **целевая** category_code; не сериализует id/version/conditions правила | [`backend/tests/integration/test_classification_rule_apply.py`](../../backend/tests/integration/test_classification_rule_apply.py) `test_preview_truncated_when_more_than_200_matches` |
| **B1** | **Bulk apply** с постраничным cursor | **есть** | `POST /rules/{id}/apply`, `has_more`, audit | [`backend/tests/integration/test_classification_rule_apply.py`](../../backend/tests/integration/test_classification_rule_apply.py) `test_apply_paginates_over_1000_transactions`, `test_apply_audit_once_per_call` |
| **B2** | **Bulk preview** перед apply | **есть** | `POST /rules/{id}/preview`, counters skipped_*, truncated | `test_preview_truncated_when_more_than_200_matches`; [`frontend/e2e/classification-polygon.spec.ts`](../../frontend/e2e/classification-polygon.spec.ts) (Проверить, отмена apply без `/apply`) |
| **B3** | **Подтверждение** массового apply (UI) | **есть** | Диалог с preview counters; «Отмена» без apply | [`frontend/e2e/classification-polygon.spec.ts`](../../frontend/e2e/classification-polygon.spec.ts) |
| **B4** | **Bulk reclassify** (отдельный сценарий) | **нет** | Только apply к неклассифицированным / без категории; массовая смена уже классифицированных — вне scope (см. FA-R06.2-B0) | — |
| **B5** | При apply **не менять** amount / date / wallet | **есть** | Обновляется только `category_id` (+ version) | [`backend/tests/integration/test_cash.py`](../../backend/tests/integration/test_cash.py) (locked + amount patch 409); apply-тесты без изменения суммы |
| **L1** | **Locked classification:** ручная классификация блокирует правило | **есть** | `POST .../classify` → `locked_classification`; import/apply skip | `test_i9_locked_classification_survives_import`; `test_apply_respects_locked_*`; [`backend/tests/integration/test_cash.py`](../../backend/tests/integration/test_cash.py) `test_version_conflict_and_classify` |
| **L2** | Locked: **race** apply vs manual | **есть** | Concurrent apply + classify → manual wins | `test_apply_does_not_overwrite_manual_classification_race` |
| **U1** | **Unclassified** в денежных итогах, снижение **completeness** категорий | **есть** | unmapped в `/cashflow`; `completeness` preliminary при unmapped | [`backend/tests/integration/test_cashflow_classification_polygon.py`](../../backend/tests/integration/test_cashflow_classification_polygon.py); [`backend/tests/integration/test_cashflow_polygon_p1.py`](../../backend/tests/integration/test_cashflow_polygon_p1.py) §3.6 / P1b |

---

## Связанные пакеты FA-R06.2 (вне буквального текста §10, но в продукте)

| Тема | Статус | Тест |
|------|--------|------|
| Idempotency **создания** правила (`Idempotency-Key`) | **есть** (B1) | [`test_create_rule_idempotent`](../../backend/tests/integration/test_classification_screen_api.py), `test_create_rule_requires_idempotency_key`, `test_create_rule_idempotency_conflict`, `test_create_rule_two_keys_same_body_creates_two_rules` |
| UI: повтор «Проверить», stale preview | **есть** (B2) | [`frontend/src/lib/classificationApply.test.ts`](../../frontend/src/lib/classificationApply.test.ts); [`frontend/e2e/classification-polygon.spec.ts`](../../frontend/e2e/classification-polygon.spec.ts) «устаревший ответ…» |

---

## Итог для планирования

- **Закрыто для Q6 / ClientBank (FA-R06.2-A):** правила при импорте + apply/preview для проведённых операций (**C1–C2, C4–C5, A1, P1–P2, P4, P6, B1–B3, B5, L1–L2, U1**).
- **Основные пробелы относительно полного §10:** C3, C6–C7, A2–A4, полноценный **E1** (persisted evidence), **P5**, **B4**, API для **tenant rules (P3)**.
- **Массовая отмена apply (B0):** отложено в [`DECISIONS.md`](DECISIONS.md) — требует миграции.

---

## Ссылки

- ТЗ §10: [financial_autopilot_complete_spec_v2_0.md §10](../../financial_autopilot_complete_spec_v2_0.md)
- ТЗ §22.4 I9 (locked): [§22.4](../../financial_autopilot_complete_spec_v2_0.md)
- Roadmap: [`DECISIONS.md`](DECISIONS.md) (FA-R06.2-A/B), [`STATE.json`](STATE.json)
