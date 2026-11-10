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
