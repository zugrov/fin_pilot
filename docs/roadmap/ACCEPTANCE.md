# Журнал доказательств приёмки (вне переписки)

Краткие ссылки на факты; подробности — в `STATE.json` и runbook'ах. Без секретов и клиентских данных в git.

---

## infra-staging-rate-limit

| Поле | Значение |
| --- | --- |
| Статус | **merged** (не deployed, не accepted) |
| PR | [#25](https://github.com/zugrov/fin_pilot/pull/25) |
| Merge SHA | `c34328f1873c636c4c23f5eb1e545cdc774e585f` |
| merged_at | 2026-11-10T05:48:49Z |
| HEAD PR (CI) | `64f4fcfdc2626258d7f8971f4f1265020194ebfc` |

**Содержание:** rate limit по реальному IP за Caddy (`TRUST_PROXY`, `TRUSTED_PROXY_CIDRS=172.18.0.0/16`); автоматизация приёмки стенда (`scripts/staging_acceptance.py`); deploy override из git; запрет `FLUSHDB` в runbook.

**Доказательства**

- CI PR #25 на `64f4fcf…`: backend, frontend, playwright — **success**
- CI `main` после squash: runs [42764456130](https://github.com/zugrov/fin_pilot/actions/runs/42764456130) (ci), [42764455872](https://github.com/zugrov/fin_pilot/actions/runs/42764455872) (e2e) — **success**
- Приёмка стенда: **PASS** по сценарию владельца (отчёт локально, `acceptance-report.md`, в git не коммитится)
- Изоляция tenant B (404 на чужой dashboard): **PASS** на предыдущей сборке стенда

**Не проверено**

- Tenant B на последней сборке после merge
- Вебхук ЮKassa с реальным IP через `X-Forwarded-For`
- Production deploy

**STATE:** ключ `infra-staging-rate-limit` в [STATE.json](STATE.json).

---

## docs-roadmap-batch-2026-11-10

| Задача | PR | Merge SHA |
| --- | --- | --- |
| Запрос клиенту FA-R03.1 S10/S11 | [#27](https://github.com/zugrov/fin_pilot/pull/27) | `f116a2f2693af6c257033659ddbe53c40d30231a` |
| ADR-004 банк vs начисление (proposed) | [#28](https://github.com/zugrov/fin_pilot/pull/28) | `c5f3f6452bef1aef74cfdde5e9ce3ed7f79ea6d2` |
| FA-R03.3 implementation scope | [#29](https://github.com/zugrov/fin_pilot/pull/29) | `f547c8e53a6b891482a9459b212eb76abb233f77` |

**Статус:** merged (docs only; не deployed, не accepted). **FA-R03.1** в STATE по-прежнему ждёт образцов; `current_stage` / `current_task` / `accepted_sha` этапов не менялись.

**CI:** backend, frontend, playwright — success на каждом PR.

**STATE:** ключ `docs-roadmap-batch-2026-11-10` в [STATE.json](STATE.json).

---

## staging-window-pr25-0022

| Поле | Значение |
| --- | --- |
| Статус | **merged** (runbook; не deployed) |
| PR | [#36](https://github.com/zugrov/fin_pilot/pull/36) |
| Merge SHA | `45f6668b27cb732b5f25fd49308dd981824c1806` |
| Runbook | [runbook-staging-window-pr25-0022-0023.md](../runbook-staging-window-pr25-0022-0023.md) |

**Содержание:** бэкап, migrate `20261110_0022`, smoke provenance/RLS, откат, чек-лист владельца + PR #25.

**Не проверено:** фактическое окно на VPS.

**STATE:** `staging_window_pr25_0022_docs` в [STATE.json](STATE.json).

---

## fa-r03-4-v1

| Поле | Значение |
| --- | --- |
| Статус | **merged** (не deployed) |
| PR | [#37](https://github.com/zugrov/fin_pilot/pull/37) |
| Merge SHA | `7258e2bb83997066ba1b541e737771078f6e628` |
| Миграция | `20261111_0023` не на стенде/проде |

**Содержание:** `source_correction_finding`, коллизии cash без UI/API.

**CI PR #37:** backend, frontend, playwright — success.

**STATE:** `fa_r03_4_v1` в [STATE.json](STATE.json). `current_stage` / `current_task` не менялись.

---

## fa-r03-2-persist-run

| Поле | Значение |
| --- | --- |
| Статус | **merged** (не deployed, не accepted) |
| PR | [#47](https://github.com/zugrov/fin_pilot/pull/47) |
| Head PR (CI) | `4cd403788b1f5825a04b3b24405bdc54c00d279c` |
| Merge SHA | `0cb5b66357f73758a3d9270be248f52fcdb65d59` |
| merged_at | 2026-11-11T09:57:59Z |
| Флаг | `RECONCILIATION_RUN_PERSIST_ENABLED` **false** по умолчанию |
| Миграция | не добавлялась; таблица из `20261110_0022` |

**Содержание:** запись прогона bank↔card51 после расчёта (`reconcile_bank_card51_for_company`). Read-only GET не пишет. Нет публичного API, UI и изменений ledger. Расхождение — quality flag, без автосвязки оплат. Повтор — новая строка, без UPDATE.

**CI PR #47** на `4cd4037…`: backend, frontend, playwright — **success** (ci `42998106382`, e2e `42998106271`).

**CI main** на `0cb5b66…`: ci [42999595253](https://github.com/zugrov/fin_pilot/actions/runs/42999595253), e2e [42999595343](https://github.com/zugrov/fin_pilot/actions/runs/42999595343) — **success**.

**Не проверено**

- Деплой и migrate на стенде
- Включение флага на стенде (только после smoke, см. runbook окна)
- Вызов сервисного пути на стенде: флаг сам по себе строку не создаёт

**STATE:** `fa_r03_2_persist_run` в [STATE.json](STATE.json). `current_stage` / `current_task` не менялись.
