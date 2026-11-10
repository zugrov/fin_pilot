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
