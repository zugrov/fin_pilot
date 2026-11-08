# Приёмка на стенде · P4 (профиль, дебиторка, порог НДС)

**Назначение:** единый прогон на **тестовых** данных (не клиент ТОПКОМ). **Без секретов** в протоколе: подставляйте идентификаторы из сессии, не копируйте `.env` и дампы в git.

**Связанные документы:** [vertical-slice-vat-profile-runbook.md](roadmap/vertical-slice-vat-profile-runbook.md), [P4-profile-reports-recon.md](roadmap/P4-profile-reports-recon.md) §10, [runbook-staging.md](runbook-staging.md).

**Ориентировочная длительность:** 2,5–4 ч (первый прогон с ручной загрузкой продаж); повторный — ~1–1,5 ч.

**Автоматизация API:** `python3 scripts/staging_acceptance.py` (см. `STAGING_*` в начале скрипта). CSV продаж: `fixtures/staging_sales_gross_only.csv`. Отчёт: `acceptance-report.md` (без секретов).

---

## 0. Плейсхолдеры

| Имя | Смысл |
| --- | --- |
| `BASE_URL` | URL стенда (`http://127.0.0.1:ПОРТ` через туннель или `http://{PUBLIC_HOST}`) |
| `COMPANY_A` / `TENANT_A` | Тестовая организация приёмки |
| `COMPANY_B` / `TENANT_B` | Вторая организация (изоляция) |
| `USER_A` / `USER_B` | Отдельные тестовые учётки |
| `PERIOD` | `2026-10-01` … `2026-10-31` (продажи — только октябрь 2026) |

---

## 1. Доступ и предусловия

| Шаг | Действие | Ожидание | ~время |
| --- | --- | --- | --- |
| 1.1 | Проверить `GET {BASE_URL}/health/live` и `/health/ready` | HTTP **200**, `{"status":"ok"}` | 2 мин |
| 1.2 | При закрытом стенде: SSH-туннель вида `ssh -N -L ЛОКАЛЬНЫЙ_ПОРТ:127.0.0.1:ПОРТ_PROXY {SSH_ALIAS}` | `BASE_URL=http://127.0.0.1:ЛОКАЛЬНЫЙ_ПОРТ` отвечает | 5 мин |
| 1.3 | Зафиксировать **product SHA** (git на сервере или label образа `finpilot-api:TAG`) | Запись в протокол приёмки | 2 мин |
| 1.4 | Флаги: `SEND_LIVE_PAYMENTS=false`, `BILLING_MODE=test` (типичный пилот) | Запись в имён переменных, **не** значений | 2 мин |

**Не выполнять** на данных клиента; суммы в протоколе — из тестового сценария ниже.

---

## 2. Регистрация и подтверждение почты

Создать `USER_A` (и позже `USER_B` для изоляции) через UI или API `POST /api/v1/auth/register`.

### 2.1 Вариант SQL (outbox, без исходящего SMTP)

Подходит, если письма остаются в `transactional_email_outbox` (`SEND_REAL_EMAIL=false` или smtp без доставки).

1. После register — в БД стенда (роль миграций / `finpilot`, **только read** на приёмке):
   - Найти последнюю строку outbox для email и `type = verify_email`.
   - Из `payload_redacted->>'link'` извлечь query-параметр `token` (как в интеграционных тестах: `backend/tests/integration/conftest.py`, `latest_verify_link`).
2. `POST /api/v1/auth/verify-email` с телом `{"token": "…"}`.

| Проверка | Ожидание |
| --- | --- |
| verify-email | **200** |
| login | **200**, cookie сессии |
| `GET /api/v1/auth/me` | `email_verified_at` задан |

**Регистрация и SMTP:** `register_user` (`auth_service.py`) **не вызывает SMTP синхронно** — пишет строку в `transactional_email_outbox` через `enqueue_email` (`outbox.py`). При `EMAIL_PROVIDER_MODE=smtp` без настроенного `SMTP_*` регистрация отвечает **200**, письмо остаётся в outbox (`status=pending`); фоновая отправка может падать, на API verify это не влияет.

**~15 мин** (с доступом к `psql` / `docker compose exec postgres`).

### 2.2 Вариант Mailpit (SMTP → локальный приёмник)

Если на стенде настроен SMTP на **Mailpit** (или аналог) и `SEND_REAL_EMAIL=true` с allowlist тестового адреса:

1. Register в UI.
2. Открыть веб-UI Mailpit, найти письмо verify.
3. Перейти по ссылке или скопировать `token` → `POST /api/v1/auth/verify-email`.

| Проверка | Ожидание |
| --- | --- |
| Письмо в Mailpit | Одно verify на тестовый адрес |
| После verify | login + запись, как в §2.1 |

**~10 мин** при уже поднятом Mailpit.

---

## 3. Тестовая организация и биллинг

| Шаг | Действие | Ожидание | ~время |
| --- | --- | --- | --- |
| 3.1 | Создать workspace / firm (product API или UI) | `COMPANY_A`, `TENANT_A` | 10 мин |
| 3.2 | Оплатить слоты и активировать фирмы (см. ниже) | `POST .../billing/companies/{id}/activate` → **200** | 10–20 мин |
| 3.3 | Подключить источник **revenue** (`dataset=revenue`), выставить `coverage_through` ≥ `2026-10-31` | Источник **200**, coverage обновлён | 5 мин |

Заголовок **`X-Tenant-Id: {TENANT_A}`** на всех запросах к компании.

### 3.2 Активация N фирм (`APP_ENV=production`, `BILLING_MODE=test`)

Код: `billing_service.checkout` / `activate_company`, `security.access.assert_finance_access` + `assert_company_paid`, `Settings.billing_bypass_allowed()` (`config.py`).

**Сколько слотов:** одна оплата на tenant — в quote укажите `companies: N` (для полного прогона скрипта и runbook: **4** — основная, спецставки, два сценария порога НДС). Каждую фирму после оплаты — `POST .../billing/companies/{company_id}/activate`.

#### (а) Обход billing guard

`billing_bypass_allowed()` = `BILLING_GUARD_BYPASS` **и** `app_env != production`. На стенде с **`APP_ENV=production` обход недоступен** — finance API требуют активный `company_entitlements` / оплаченный период. В production задавать `BILLING_GUARD_BYPASS` **запрещено** (`model_post_init`).

#### (б) SQL (минимально, с откатом)

Только приёмочное окно, роль `finpilot` (не `finpilot_app`). Воспроизводит результат `_grant` после успешной оплаты — **без** подмены webhook. Псевдошаги (подставьте `TENANT_ID`, `COMPANY_ID`, суммы из тарифа):

1. Убедиться, что есть `subscriptions` для tenant и текущее `now()` внутри будущего `billing_periods`.
2. Вставить `billing_periods` (`status=active`, `company_limit=N`, границы периода, `paid_amount` из quote).
3. Обновить `subscriptions.paid_through`, `company_limit`, `status=active`.
4. Для каждой фирмы — `company_entitlements` (`active`, `active_until = period.end_at`) и `companies.status=active`.

**Откат** (в той же транзакции приёмки или сразу после теста): удалить вставленные `company_entitlements` и `billing_periods` по `id`, вернуть `companies.status=draft`, **не** трогать боевые платежи. Зафиксируйте `id` строк в протоколе (UUID без клиентских данных).

Детали тарифа и полей — `backend/app/services/billing_service.py` (`_grant`, `_covering`). Предпочтительнее вариант (в), если настроена тестовая ЮKassa.

#### (в) Checkout + webhook (реализовано в `scripts/staging_acceptance.py`)

Условия стенда: `SEND_LIVE_PAYMENTS=true`, тестовые `YOOKASSA_*`, `BILLING_MODE=test` (платёж с `"test": true` проходит `_mode_problem`). При `SEND_LIVE_PAYMENTS=false` checkout вернёт **503** (`DisabledPaymentProvider`) — тогда (б) или включить тестовую интеграцию на окно приёмки.

Последовательность:

1. `POST /api/v1/billing/quote` с `{"companies": N, "interval": "month", ...}`.
2. `POST /api/v1/billing/checkout` → в теле **`payment_id`** (UUID попытки в БД).
3. Прочитать **`provider_payment_id`**:  
   `SELECT provider_payment_id FROM payment_attempts WHERE id = '<payment_id>';`  
   (на тестовом стенде ЮKassa — тот же id, что в ответе `create_payment`, если платёж создан).
4. `POST /api/v1/integrations/yookassa/webhook` с `{"event":"payment.succeeded","object":{"id":"<provider_payment_id>"}}` — запись в inbox; обработка в `billing_service.process_inbox` / worker `billing.process_inbox` (до ~60 с).
5. `GET /api/v1/billing/payments/{payment_id}` → `"activated": true`.
6. Для каждой фирмы: `POST /api/v1/billing/companies/{id}/activate`.

Переменные скрипта: `STAGING_BILLING_COMPANIES` (по умолчанию 4), `STAGING_PROVIDER_PAYMENT_ID`, `STAGING_SKIP_BILLING=1` — только повторный `activate`, если период уже оплачен.

---

## 4. Продажи октября 2026 (только брутто)

Цель: gross-only строки (`amount_inc_vat`, `vat_basis: unknown`, без `amount_ex_vat`).

**Минимальный набор для §8:**

- Несколько продаж в октябре с разными датами (например **10 000,00** и **5 000,00**) — baseline dashboard.

**Дополнительно для порога НДС** (отдельные идемпотентные POST или импорт, **по согласованию** на стенде):

| Сценарий | Сумма YTD (пример) | Назначение |
| --- | --- | --- |
| approaching | **16 500 000,00** (или накопление YTD с начала года) | `vat_threshold.status = approaching` |
| exceeded | **21 000 000,00** | `status = exceeded`, `obligation_from` следующий месяц |

Суммы — **строки** в API; в протоколе фиксируйте только флаги и статусы, не обязательно полный журнал.

**~20–40 мин** (ручной ввод / CSV).

---

## 5. Мастер профиля · черновик без эффекта

`PATCH .../organization-profile/draft` — USN, `vat_status: not_applicable` (см. [vertical-slice-vat-profile-runbook.md](roadmap/vertical-slice-vat-profile-runbook.md) §3).

| Проверка | Ожидание |
| --- | --- |
| Dashboard `PERIOD` | Как **до** мастера: есть **`vat_basis_unknown`**, нет **`vat_basis_from_profile`**, `metric_basis = source` |
| AR `GET .../reports/receivable-aging?as_of=2026-10-31` | Флаги согласованы с dashboard; подпись **«Остаток (с НДС)»** при unknown |

**~15 мин**

---

## 6. Подтверждение профиля · `not_applicable`

`POST .../organization-profile/versions/{VERSION_ID}/confirm` (CSRF + `Idempotency-Key`).

| Проверка | Ожидание |
| --- | --- |
| Dashboard `PERIOD` | **Нет** `vat_basis_unknown`; есть **`vat_basis_from_profile`**; `metric_basis = net`; `revenue_label` про выручку без НДС; **`input_revision` изменился** |
| Обзор UI | Блок «Состояние данных» — человекочитаемые флаги |
| AR | **`vat_basis_from_profile`**; подпись **«Остаток (НДС не применяется)»**; **суммы gross не меняются** |
| Group-summary за `PERIOD` | Те же revenue-флаги, что dashboard |

**~15 мин**

---

## 7. Спецставки НДС (`special_rates_5_7`) · отдельная фирма

**Не** менять профиль фирмы A после шага 6. Создайте **`COMPANY_SPECIAL`**: gross-only продажа, профиль УСН, `vat_status: special_rates_5_7`, draft + confirm.

| Проверка | Ожидание |
| --- | --- |
| Dashboard / AR | **`vat_basis_unknown` есть**; **`vat_basis_from_profile` нет** |
| UI | Без ложного снятия предупреждения на Обзоре |

**~15 мин**

Фирма A остаётся с подтверждённым `not_applicable` для сравнения в протоколе.

---

## 8. Порог НДС (волна 2)

Профиль: **USN** + подтверждённый **`not_applicable`**. Период дашборда с `date_from` = начало календарного года `date_to` в 2026 (или год периода по [P4](roadmap/P4-profile-reports-recon.md)).

| Состояние YTD | Ожидание в JSON `vat_threshold` |
| --- | --- |
| Ниже порога (нет данных / малый объём) | Блок **отсутствует** |
| ≥ ~80 % порога (тест **16 500 000,00**) | `status: approaching`, `disclaimer: usn_accrual_vs_cash`, `as_of`, `threshold` и `ytd_revenue` строками |
| Выше порога (**21 000 000,00**) | `status: exceeded`, `exceeded_month`, `obligation_from` |
| `vat_payer` / ОСНО | Блок **отсутствует** |
| UI Обзор | `data-testid="vat-threshold-banner"` при approaching/exceeded |

**~25–45 мин** (зависит от загрузки YTD).

---

## 9. Изоляция второго tenant

| Шаг | Действие | Ожидание |
| --- | --- | --- |
| 9.1 | Register + verify `USER_B`, создать `COMPANY_B` / `TENANT_B` | Отдельное пространство |
| 9.2 | `GET .../companies/{COMPANY_A}/dashboard` с `X-Tenant-Id: {TENANT_B}` | **404** `not_found` |
| 9.3 | Dashboard B без профиля A | **Нет** `vat_basis_from_profile` от чужой фирмы |

**~20 мин**

---

## 10. Ручной проход в браузере (~10–15 мин)

Дополняет API-скрипт; URL через туннель (`BASE_URL`). Тестовый пользователь после verify и оплаты слота.

| # | Действие | Ожидание |
| --- | --- | --- |
| 1 | Вход, выбор фирмы A, период октябрь 2026 | Обзор загружается без 5xx |
| 2 | До подтверждения профиля | Баннер **`data-testid="org-profile-overview-banner"`**; в «Состоянии данных» — признак unknown НДС |
| 3 | Мастер профиля → УСН → `not_applicable` → **подтвердить** | Баннер профиля **исчезает** |
| 4 | Обзор и **Дебиторка** | Флаги согласованы с §5–6; после confirm нет ложного «с НДС» на итоге AR |
| 5 | Фирма с YTD для порога (или A после догрузки) | Баннер **`data-testid="vat-threshold-banner"`**, дисклеймер про начисление vs кассу |
| 6 | Ссылка «Открыть мастер профиля» (из баннера порога или профиля) | Переход на мастер, без обрыва сессии |

Скриншоты — в `var/acceptance-…/` (вне git).

---

## 11. Что сохранить перед выключением стенда

Артефакты **вне git** (каталог вроде `var/acceptance-YYYYMMDD/`):

| Артефакт | Зачем |
| --- | --- |
| **Дамп БД** | `pg_dump` custom или `docker compose exec -T postgres pg_dump -U finpilot -Fc finpilot > backup.dump` |
| Копия **`.env`** (шифрованный том / менеджер секретов) | Восстановление паролей БД и ключей |
| Product **SHA**, теги образов `finpilot-api` / `finpilot-frontend` | Воспроизводимость |
| Краткий **протокол**: pass/fail по §§5–9, `COMPANY_*` UUID, redacted JSON фрагменты | Аудит приёмки |
| Скриншоты UI (баннер порога, флаги Обзора) | Опционально |

Перед `compose down` / остановкой VPS убедиться, что дамп проверен (`pg_restore -l`).

---

## 12. Критерий «принято»

- Все таблицы ожиданий §§5–9 — **pass** на зафиксированном SHA.
- Нет записей клиентских контрагентов / назначений платежей в протоколе.
- Ограничения зафиксированы: один стенд, тестовые учётки, октябрь 2026 gross-only для базового §8; порог YTD — осознанная догрузка.
