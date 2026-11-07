# Runbook §8 · приёмка `vat_basis_from_profile` на дашборде

**Для кого:** приёмочная организация владельца (не данные клиента).  
**Контур:** HTTP API v1, права owner/accountant, подтверждённая почта на запись.

Связанные документы: [vertical-slice-vat-profile.md](vertical-slice-vat-profile.md), [ADR-003](ADR-003-organization-profile-and-tax-rules.md).

---

## 1. Предусловия

1. Активированная фирма и биллинг (как в пилоте).
2. Источник **revenue** с `coverage_through` не раньше конца проверяемого периода.
3. В журнале есть строки выручки с `vat_basis: unknown` и суммой только **брутто** (`amount_inc_vat` без `amount_ex_vat`) — типичный gross-only импорт.
4. Сессия пользователя: cookie сессии + заголовок **`X-Tenant-Id`** (пространство фирмы).
5. На **мутациях** профиля: **`X-CSRF-Token`** из ответа логина; на **confirm** и идемпотентных POST — **`Idempotency-Key`** (уникальная строка на запрос).

Без секретов в примерах: подставьте `COMPANY_ID`, `VERSION_ID`, токены из своей сессии.

---

## 2. Снимок «до» (неподтверждённый профиль)

```http
GET /api/v1/companies/{COMPANY_ID}/dashboard?date_from=2026-10-01&date_to=2026-10-31
X-Tenant-Id: {TENANT_ID}
```

**Ожидание:**

- `quality_flags` содержит **`vat_basis_unknown`**;
- **нет** `vat_basis_from_profile`;
- `revenue_label` ≈ «сумма продаж по данным источника»;
- `metric_basis` = **`source`**.

---

## 3. Заполнить черновик профиля

```http
PATCH /api/v1/companies/{COMPANY_ID}/organization-profile/draft
Content-Type: application/json
X-Tenant-Id: {TENANT_ID}
X-CSRF-Token: {CSRF_FROM_LOGIN}

{
  "org_form": "ooo",
  "tax_system": "usn",
  "usn_tax_object": "income",
  "vat_status": "not_applicable",
  "accounting_source": "onec",
  "money_channels": ["bank"],
  "month_close_policy": "calendar_month_end",
  "revenue_recognition_method": "accrual",
  "is_new_organization": true,
  "change_reason": "приёмка §8"
}
```

Ответ **200**; версия остаётся неподтверждённой (`confirmed_at` пусто в `GET .../organization-profile`).

**Проверка:** повторить dashboard — поведение **как в §2** (защита пилота).

---

## 4. Подтвердить версию

Список версий:

```http
GET /api/v1/companies/{COMPANY_ID}/organization-profile/versions
X-Tenant-Id: {TENANT_ID}
```

Подтверждение (берём `version_id` последней версии):

```http
POST /api/v1/companies/{COMPANY_ID}/organization-profile/versions/{VERSION_ID}/confirm
X-Tenant-Id: {TENANT_ID}
X-CSRF-Token: {CSRF_FROM_LOGIN}
Idempotency-Key: {UNIQUE_KEY}
```

Ответ **200**; в профиле появляются `confirmed_at`, `confirmed_role`.

---

## 5. Снимок «после» (подтверждённый `not_applicable`)

Тот же dashboard за тот же период и **те же строки** выручки:

**Ожидание (все строки gross-only, один месяц, профиль подтверждён):**

- **нет** `vat_basis_unknown`;
- есть **`vat_basis_from_profile`**;
- `revenue_label` = **«Выручка без НДС»**;
- `metric_basis` = **`net`**;
- сумма `values.revenue` = сумма брутто продаж (НДС не применяется → брутто = выручка без НДС в срезе §8);
- `input_revision` **изменился** (в хеше участвует `revenue_profile`).

На экране **Обзор** в блоке «Состояние данных» — человекочитаемые подписи флагов (см. `overview.ts`).

---

## 6. Негативные контрольные точки

| Сценарий | Ожидание |
| --- | --- |
| `vat_status: special_rates_5_7` (подтверждён) | `vat_basis_unknown` **остаётся**, оверлея нет |
| Черновик без confirm | как §2 |
| Смесь нетто-строки и gross-only в разных месяцах | gross-представление (`source`), оба флага `vat_basis_unknown` и `vat_basis_from_profile` |
| `GET .../workspaces/{tenant}/group-summary` за тот же период | те же флаги и `metrics.revenue`, что на dashboard |

---

## 7. Освобождение по ст. 145 (опционально §8)

Если в профиле `vat_status: exemption` и **`vat_exemption_article_145: true`**, после confirm — те же признаки, что в §5 для `not_applicable` (на gross-only данных).  
Обычный `exemption` без ст. 145 в §8 **не** меняет флаги.

---

## 8. Изоляция

Пользователь пространства **B** не должен получать `200` на dashboard компании **A** (`404 not_found`). Профиль **A** не добавляет `vat_basis_from_profile` на выручку **B**.
