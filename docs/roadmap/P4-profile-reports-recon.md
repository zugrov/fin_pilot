# P4 · Профиль организации в отчётах и сверках (разведка)

**Статус:** разведка и план волн (**без кода** в этом PR).  
**Основание:** [ADR-003](ADR-003-organization-profile-and-tax-rules.md), [ADR-002](ADR-002-acquiring-revenue-from-bank-statement.md), [FA-R06.1](FA-R06.1-management-rules-v1.md), [vertical-slice-vat-profile.md](vertical-slice-vat-profile.md).  
**Контекст `main`:** P3c смержен (`1fc0d7c`), OpenAPI **122** (без изменений в P4-разведке).

---

## 1. Зачем P4

Мастер и карточка профиля (P3) задают **снимок правил** по месяцам. Отчёты и сверки пока в основном опираются на **факты импорта** и домен `assess_revenue` без полной связки со всеми полями профиля. P4 фиксирует:

- где уже есть влияние профиля;
- что переносить волнами;
- что остаётся `unavailable` и как не ломать **защиту пилота** (неподтверждённый / неполный профиль → поведение как сейчас).

**Защита пилота (сквозное правило):** оверлей и подсказки из подтверждённого профиля **не** применяются, пока на месяц строки/периода нет **подтверждённой** версии с `effective_from ≤ месяц` (см. `resolve_profile_for_period`). Черновик и `unspecified`/`unknown` в критических полях → прежние флаги, баннеры, gross-подписи.

---

## 2. Инвентаризация контуров

| Контур | Где логика (backend) | API / UI | Текущие `quality_flags` / полнота | Поля профиля (влияние сейчас / целевое) | Уже с профилем |
| --- | --- | --- | --- | --- | --- |
| **ОПиУ / выручка (Обзор)** | `report_service.revenue_snapshot`, `domain/revenue.assess_revenue`, `domain/org_profile/revenue_vat_overlay` | `GET .../dashboard`, `OverviewPage` | `missing_revenue_source`, `partial_period`, **`vat_basis_unknown`**, **`vat_basis_from_profile`** (инфо) | **`vat_status`**, **`vat_exemption_article_145`** (§8); целевое: `prices_include_vat`, `revenue_recognition_method` (подписи «поступления ≠ выручка») | **Да** — срез §8 ([vertical-slice-vat-profile.md](vertical-slice-vat-profile.md)) |
| **Дебиторка** | `receivable_aging_service` | `GET .../reports/receivable-aging`, `ReceivablePage` | `missing_revenue_source`, `partial_period`, `missing_counterparty`, completeness `preliminary` / `full` / `unavailable`; **баланс всегда gross** (`amount_inc_vat`) | Целевое: согласование подписи с **`vat_basis_unknown`** / оверлеем профиля (FA-R06.1 §4.6); `revenue_recognition_method` — якорь aging vs касса (инфо) | **Нет** (gross по спецификации, флаг не пробрасывается из revenue) |
| **ОДДС** | `report_service.cashflow_payload`, `cash_service` | `GET .../cashflow`, `CashflowPage` | `missing_opening_balance`, `partial_period`, `unclassified_operations`, `stale_cash_source`, completeness | Целевое: **§5.1** — секции налоговых платежей по **`tax_system`**, **`vat_status`**; **`money_channels`** — маршрут сверок; `month_close_policy` — `preliminary` после закрытия | **Нет** |
| **Бюджет** | `budget_service`, `domain/budget` | `GET/POST .../budgets`, Budget UI | Свои flags по покрытию факта vs план (`missing_*`, сравнение периода) | Целевое: шкала сравнения с фактом выручки через **`revenue_recognition_method`**, предупреждение при `vat_basis_unknown` на факте | **Нет** |
| **Сводка по группе** | `companies.group_summary`, агрегация `revenue_snapshot` / cash | `GET .../workspaces/{tid}/group-summary` | Объединение flags фирм; revenue flags как на dashboard | Те же, что выручка + изоляция tenant; нет группового «профиля» | **Частично** (revenue §8 на фирму) |
| **Telegram-дайджест / бот** | `telegram_digest.py`, `telegram_bot.py` → `revenue_snapshot` | jobs, preview API | Как dashboard MTD/day revenue | Как выручка §8; `money_channels`/`accounting_source` — тексты рекомендаций (будущее) | **Частично** (revenue) |
| **Прогноз / касса на дату** | `forecast_service`, `company_summary` | forecast API | `missing_opening_balance`, отдельный `input_revision` | В §8 **не** входит `revenue_profile_revision`; целевое P4.2+ — только баннеры, без пересчёта прогноза | **Нет** |
| **Классификация ОДДС** | правила / unclassified summary | `ClassificationPage`, summary API | `unclassified_operations` | **§5.2** — шаблоны по **`org_form` × `tax_system` × `vat_status` × `money_channels`** | **Нет** |
| **Сверка эквайринга (ADR-002)** | импорт ClientBank, полигон; эталон 57.03 | в основном импорт / будущие отчёты | `reconciliation_difference`, `unavailable` по ADR-002 | **`money_channels`** ⊃ `acquiring`, **`accounting_source`**, **`prices_include_vat`**, **`vat_status`** | **Нет** (чеклист в UI: `orgProfileExportPreview`) |

### 2.1 Frontend: качество на экранах

| Экран | Модуль | Флаги |
| --- | --- | --- |
| Обзор | `frontend/src/lib/overview.ts` | `vat_basis_unknown`, `vat_basis_from_profile`, cash/revenue merge из dashboard |
| Дебиторка | `receivable.ts`, страница AR | completeness; **нет** текста `vat_basis_unknown` |
| ОДДС | `cashflow.ts` | partial, unclassified, opening balance |
| Бюджет | `budget.ts` | отклонения план/факт |

---

## 3. Уже сделано (носитель A, волна 0)

См. [vertical-slice-vat-profile.md](vertical-slice-vat-profile.md):

- Построчный оверлей после `assess_revenue` для **подтверждённого** `vat_status = not_applicable` (и ст. 145 по приёмке).
- `revenue_profile_revision` в `input_revision` дашборда, group-summary, digest.
- Unit/integration: `test_revenue_vat_profile_overlay.py`, `test_org_profile_vat_vertical_slice.py`; UI `overview.test.ts`.

**Не сделано в §8:** дебиторка, ОДДС, бюджет, классификация, ADR-002, §5.1–5.2.

---

## 4. Предлагаемый порядок волн

**Порядок:** 1 дебиторка → 2 мониторинг порога НДС для УСН → 3 метки ОДДС → 4 эквайринг → 5 классификация → 6 бюджет.

### Волна 1 · Дебиторка и согласованность НДС (узкий срез)

| | |
| --- | --- |
| **Минимальное изменение** | По строкам с ненулевым остатком — месяцы `recognition_date` → `resolve_profiles_for_months` и общая проверка применимости оверлея (`profile_vat_overlay_applies` / `row_vat_basis_unknown` из `revenue_vat_overlay`). Флаги `vat_basis_unknown` / `vat_basis_from_profile` в существующем `quality_flags`; **суммы остатка не менять**. UI: `receivable.ts`, `ReceivablePage` — тексты как на Обзоре; подпись итога: при `vat_basis_unknown` — **«Остаток (с НДС)»**; при одном `vat_basis_from_profile` (без unknown) — **«Остаток (НДС не применяется)»** (без «с НДС»). |
| **Соответствие FA-R06.1 §4.6** | Выставление `vat_basis_unknown` в дебиторке **без** подтверждённого профиля — **приведение к спецификации** (gross-only строки, суммы как сейчас), а **не** оверлей профиля. Оверлей §8 на AR **не** пересчитывает balance в net. |
| **Риски** | Двойная трактовка net/gross на одном экране; производительность (доп. запрос версий — переиспользовать `resolve_profiles_for_months`) |
| **Тесты** | Unit выбора флагов; integration на полигоне (без профиля, `not_applicable`, spec rates, две версии по месяцам); регресс ORACLE дебиторки; vitest текстов; Playwright **не** требуется |
| **Объём** | **S** (1–2 недели): backend read-model + UI copy, OpenAPI **122** без новых полей ответа |
| **Защита пилота** | Без подтверждённого профиля на месяц строки — `vat_basis_unknown`, gross, как сейчас |

**Приёмка на стенде после волны 1:** прогон [vertical-slice-vat-profile-runbook.md](vertical-slice-vat-profile-runbook.md) + сценарии AR из §10 п.1–4.

### Волна 2 · Мониторинг порога НДС для УСН

| | |
| --- | --- |
| **Минимальное изменение** | На **Обзоре**: накопленная с начала календарного года **выручка** по датам признания из `revenue_snapshot` против `usn_vat_exemption_threshold_rub` из `GET /tax-norms/current` на дату среза. Предупреждения при **≥ 80 %** порога и при **превышении** (обязанность по НДС — с **первого числа месяца, следующего за месяцем превышения**, ADR-003 §4.1). Показывать только при **подтверждённом** профиле с `tax_system=usn` и `vat_status ∈ {not_applicable, exemption}`. Обязательная пометка: **«Ориентир: налоговая база УСН считается по поступлениям, а выручка здесь — по датам признания»**. |
| **Риски** | Путаница касса vs начисление; устаревший справочник норм; ложное «обязаны» при неполном импорте выручки |
| **Тесты** | Unit порога и даты обязанности; integration с mock норм и YTD-срезом; UI copy на Обзоре; без смены сумм KPI |
| **Объём** | **S–M**: read-модель + баннер/блок на `OverviewPage`, OpenAPI по необходимости только для metadata (не новый endpoint) |
| **Защита пилота** | Иной `tax_system` / `vat_status`, черновик профиля, `unavailable` нормы — блок **скрыт** или `unavailable` с пояснением |

### Волна 3 · ОДДС: метки режима (ADR-003 §5.1)

| | |
| --- | --- |
| **Минимальное изменение** | Справочник «упрощённая схема» секции для строк с `category_code` ∈ {налоги, УСН, НДС…} по **`tax_system`** + **`vat_status`**; иначе `unavailable` с пояснением. Без автопереклассификации проводок |
| **Риски** | Юридическая неточность → явная метка «не налоговая консультация»; спорные платежи |
| **Тесты** | Unit таблицы соответствия; cashflow polygon без смены сумм |
| **Объём** | **M**: домен + отображение в `cashflow_payload` metadata |
| **Защита пилота** | `tax_system` / `vat_status` unknown → секция подсказки **скрыта** (`unavailable`), обороты как сейчас |

### Волна 4 · Эквайринг (ADR-002) × профиль

| | |
| --- | --- |
| **Минимальное изменение** | Включение блока сверки 57.03 только если **`money_channels`** содержит `acquiring` и **`accounting_source`** ∈ {`onec`, `cloud` с ОСВ}; иначе заглушка «недоступно для профиля». Допуски §3 ADR-002 без изменения |
| **Риски** | Ложная «сверена» без ОСВ; облако без экспорта |
| **Тесты** | Полигон retail + mock выписки; негатив без 57.03 |
| **Объём** | **M–L** (зависит от наличия агрегата в импорте) |
| **Защита пилота** | Нет канала / неподтверждённый профиль → блок не показываем или `unavailable` |

### Волна 5 · Классификация (ADR-003 §5.2)

| | |
| --- | --- |
| **Минимальное изменение** | Каталог **рекомендованных** наборов правил (read-only подсказка + deep link в классификацию), без автозаписи в БД |
| **Риски** | Пользователь ожидает автоприменение |
| **Тесты** | Табличные unit по комбинациям профиля |
| **Объём** | **M** (конфиг + UI) |
| **Решение владельца** | Какие наборы N… и можно ли «применить одним кликом» |

### Волна 6 · Бюджет и расширенные подписи

| | |
| --- | --- |
| **Минимальное изменение** | При сравнении с фактом выручки — та же `label`/`metric_basis`, что dashboard; предупреждение при расхождении шкалы |
| **Объём** | **S** после волны 1 |

**`revenue_recognition_method`:** отдельная подпись на Обзоре/ОДДС «поступления ≠ выручка» — **волны 2–6** (информационная; без смены цифр без импорта).

**`industry_sphere`:** персональный список выгрузок уже в мастере (`orgProfileExportPreview`); в отчёты — не раньше волны 4.

**`usn_tax_object`:** влияет на расходный контур (FA-R06.2 / ОПиУ расширенный) — **за горизонтом P4**, только флаги «расходы недоступны».

---

## 5. ADR-003 §5.1 — налоговые платежи и секции ОДДС

| Реализуемо без новых данных | Требует решения владельца |
| --- | --- |
| Таблица подсказок «операционная / финансовая» для **типовых** кодов классификации при **`tax_system=usn`** vs **`osno`** и **`vat_status`** из профиля | Спорные платежи (займы vs взносы), региональные льготы |
| Метка «упрощённая схема» в UI | Автоматическое изменение `category_code` в БД |
| Скрытие блока при `unconfirmed` профиле | Единая политика для УСН + обязательный НДС (см. ADR §4) |

---

## 6. ADR-003 §5.2 — наборы правил классификации

| Реализуемо без новых данных | Требует решения владельца |
| --- | --- |
| Статический каталог «набор **N**» по ключу профиля (как в ADR) | Привязка к существующим rule id в проде |
| Показ «рекомендовано для вашего профиля» на `/classification` | Массовое применение шаблона и откат |
| Учёт только **`money_channels`** + **`tax_system`** в v1 каталога | Полная матрица × `org_form` |

---

## 7. Сверка эквайринга (ADR-002)

| Условие профиля | Поведение (черновик P4) |
| --- | --- |
| `money_channels` без `acquiring` | Блок сверки **не показывать**; ADR-002 не активен |
| `acquiring` + `accounting_source=book_csv` | Только выписка, признак `рассчитано_по_выписке`; допуски §3 |
| `acquiring` + `onec`/облако с ОСВ | Эталон 57.03, §3.2 приоритет учёта |
| `prices_include_vat` / `vat_status` | Одна шкала за период; при конфликте с фактом revenue — `reconciliation_difference` + баннер |
| Профиль не подтверждён | Сверка **не** «зелёная» автоматически; допуски без снятия quality flags |

---

## 8. Дебиторка и `vat_basis_unknown` (FA-R06.1 §4.6)

**Спецификация:** при `vat_basis_unknown` balance в **gross** с подписью; флаг **сохраняется**.

**Сейчас:**

- Расчёт balance: gross `amount_inc_vat` — **соответствует**.
- Флаг `vat_basis_unknown` в AR payload **не выставляется** (логика только в `assess_revenue`).
- UI не дублирует пояснение из Обзора.

**Целевое (волна 1):**

1. Для `as_of` определить месяцы по строкам sales/returns с ненулевым остатком → `resolve_profiles_for_months`.
2. Для gross-only: если оверлей §8 на месяц recognition применим — **`vat_basis_from_profile`**; если нет — **`vat_basis_unknown`**. Возможны **оба** флага при смеси месяцев/режимов (как на Обзоре).
3. Подпись итога: **`vat_basis_unknown`** → «Остаток (с НДС)»; **только** `vat_basis_from_profile` → «Остаток (НДС не применяется)»; пояснения из `FLAG_TEXT` как на Обзоре.
4. **Не** пересчитывать balance в net на AR (отличие от revenue aggregate). Без профиля — только приведение к §4.6 (`vat_basis_unknown`), не оверлей.

---

## 9. Что остаётся `unavailable` до волны 2+ (и UI)

| Возможность | До какой волны | Как показывать пользователю |
| --- | --- | --- |
| Мониторинг порога НДС при УСН | Волна 2 | На Обзоре: блок скрыт или «Недоступно» без подтверждённого USN-профиля в `not_applicable` / `exemption` |
| Подсказки секций налогов в ОДДС | Волна 3 | Секция «Налоги и взносы»: «Недоступно — уточните режим в профиле»; обороты без изменений |
| Сверка эквайринга 57.03 | Волна 4 | Карточка на импорте/деньгах: `unavailable` + ссылка «Профиль организации» |
| Рекомендованный набор классификации | Волна 5 | Баннер info на `/classification` |
| Net-дашборд дебиторки при gross-only | Не планируется в P4 | Явная подпись gross |
| НДС с вычетами (полный ОСНО) | ADR §7 ✗ | `support_level` / `unavailable` на НДС-блоках |
| Автопересчёт закрытых периодов при смене профиля | **Никогда** (ADR §3) | Текст в карточке профиля |

---

## 10. Сценарии приёмки (тестовая организация E2E)

База: полигон / E2E **Альфа**, timezone **Europe/Moscow**, отдельные сценарии с mock профиля (как P3c).

**После волны 1 (стенд):** прохождение [vertical-slice-vat-profile-runbook.md](vertical-slice-vat-profile-runbook.md) и пункты 1–4 ниже на той же фирме.

1. **Неподтверждённый профиль:** dashboard и AR — `vat_basis_unknown` на gross sale; нет `vat_basis_from_profile`; баннер Обзора активен; подпись AR «Остаток (с НДС)».
2. **Подтверждённый USN `not_applicable`:** dashboard снимает флаг; AR — `vat_basis_from_profile`, balance gross **без изменения суммы**, подпись «Остаток (НДС не применяется)».
3. **`special_rates_5_7`:** dashboard сохраняет `vat_basis_unknown`; AR — то же.
4. **Две версии по месяцам (октябрь/ноябрь):** revenue построчно; AR `as_of` на границе месяцев — флаги по месяцу recognition (в т.ч. оба флага при смеси).
5. **Group-summary:** те же revenue flags, что dashboard, на той же фирме.
6. **Digest MTD:** совпадение с dashboard revenue block.
7. **Порог НДС (волна 2):** USN + `not_applicable`, YTD выручка 80 % и 100 %+ порога — warn и дата обязанности; дисклеймер про поступления vs признание; ОСНО / `vat_payer` — блок скрыт.
8. **ОДДС (волна 3):** при подтверждённом USN — метки секций; при черновике — блок unavailable.
9. **Эквайринг (волна 4):** профиль без `acquiring` — нет блока сверки; с `acquiring` + retail полигон — допуски ADR-002.

---

## 11. Открытые вопросы к владельцу (с рекомендациями)

| # | Вопрос | Рекомендация |
| --- | --- | --- |
| Q1 | Дебиторка: показывать ли **справочную** колонку net ex-VAT при оверлее §8? | **Нет в v1** — только флаги и подпись gross (меньше путаницы) |
| Q2 | §5.1: автосмена `category_code` или только подписи? | **Только подписи** в волне 2 |
| Q3 | §5.2: кнопка «Применить набор N»? | **Отложить**; волна 4 — read-only рекомендация |
| Q4 | Эквайринг без ОСВ: доверять выписке в UI как «официальной»? | **Да**, с бейджем `рассчитано_по_выписке` (ADR §3.2) |
| Q5 | Бюджет: блокировать approve при `vat_basis_unknown` на факте? | **Нет** — warn only |
| Q6 | `exemption` без ст. 145 в §8 | **Не снимать** флаг (как в vertical-slice) до отдельного ADR |
| Q7 | Группа: агрегировать «профиль подтверждён» на уровне tenant? | **Нет** — по каждой фирме; group только revenue flags |

---

## 12. Файлы-якоря (для реализации волн)

| Область | Файлы |
| --- | --- |
| Revenue + overlay | `backend/app/domain/org_profile/revenue_vat_overlay.py`, `report_service.revenue_snapshot` |
| Профиль | `org_profile_service.resolve_profiles_for_months`, `resolution.py` |
| Dashboard / group | `companies.py`, `dashboard_payload` |
| AR | `receivable_aging_service.py` |
| ОДДС | `report_service.cashflow_payload` |
| Telegram | `telegram_digest.py`, `telegram_bot.py` |
| UI качество | `frontend/src/lib/overview.ts`, `receivable.ts`, `cashflow.ts` |
| E2E профиля | `frontend/e2e/org-profile-wizard.spec.ts` |

OpenAPI **122** менять только при новых полях ответа; волна 1 — в рамках существующих `quality_flags`; волна 2 — по необходимости metadata на dashboard без нового endpoint.

---

## Связанные документы

- [P3-wizard-spec.md](P3-wizard-spec.md)
- [profile-implementation-plan.md](profile-implementation-plan.md)
- [FA-R03.2-export-checklist-by-profile.md](FA-R03.2-export-checklist-by-profile.md)
- [accounting-policy.md](../accounting-policy.md)
