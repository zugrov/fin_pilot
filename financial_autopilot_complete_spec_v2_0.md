# Единое техническое задание для Cursor
# «Финансовый автопилот» — финансовый учёт, прогноз и Telegram для МСБ

Версия: 2.0, единая редакция. Дата: 14 октября 2026.
Заказчик: Макс Зугров. Язык продукта: русский. Валюта первой версии: RUB.
Назначение: основной документ для разработки, тестирования и запуска платной beta.

Этот документ объединяет инженерное ТЗ 1.0, billing/email дополнение 1.1 и годовой тариф 1.2. При конфликте с прежними документами действует эта единая редакция. Отдельные дополнения для реализации не нужны.

Годовая скидка 15% утверждена заказчиком 14.10.2026. Это действующее требование, не тестовое допущение.

## 0. Основания, подтверждённые требования и проектные решения

Функциональный референс — приложенный скриншот проекта Марии Паушевой: отчёты 1С из почты, классификация, Telegram-ввод, кошельки, движение денег, планирование, минимальный остаток и права. [file:2]
Продуктовый контекст — «Продуктовое ТЗ_ «Финансовый автопилот» для МСБ в Р.md»: ежедневное управление ликвидностью, 1С-first, прогноз, budgets, алерты, объяснимость и read-only источники. [file:1]

Обязательные требования заказчика:
- аналог сервиса финансового учёта и планирования со скриншота;
- одна или несколько фирм в рабочем пространстве;
- ежедневный Telegram-дайджест собственнику: остатки, кассовые разрывы, выручка, аномалии, бюджетные отклонения и качество данных;
- платная beta через ЮKassa;
- первая фирма 2500 RUB, каждая последующая 1500 RUB по базовому месячному тарифу;
- авторизация через email;
- годовая оплата, скидка 15% утверждена.

Ежемесячный базовый период принят в предыдущих редакциях как рабочая модель и используется вместе с годовой оплатой. Остальные не заданные заказчиком политики ниже — проектные defaults: email/password, ИП как одна фирма, prorata upgrades, grace 3 дня, ручное продление, отсутствие отдельной платы за сотрудников. Их нельзя выдавать за внешние нормы. При изменении политики обновляются документ, оферта и тесты.
Налоговые реквизиты продавца, receipt scenario, реальный шаблон 1С и инфраструктурные secrets уточняются до live запуска. Эти зависимости не блокируют разработку на test/mock.
Архитектура и пороги — требования к новому продукту, не установленные свойства референса. Юридическое соответствие не заявляется без отдельной проверки.

## 1. Цель и границы продукта

Создать веб-приложение и Telegram-бота для собственника, финансиста и бухгалтера. Ежедневно отвечать:
1. Сколько денег есть, где они находятся, сколько доступно?
2. Что произошло вчера и с начала месяца?
3. На какие выплаты хватит денег и когда возникнет дефицит?
4. Как факт отличается от бюджета?
5. Какие операции/изменения требуют проверки?
6. Насколько актуальны, полны и согласованы данные?

Продукт — управленческая надстройка. Не заменяет бухгалтерию, не сдаёт отчётность, не исправляет документы в 1С и не исполняет банковские платежи за клиента. Приём оплаты самого SaaS через ЮKassa — отдельная обязательная функция.

### 1.1. Обязательный объём платной beta
- email register/verify/login/reset, invitations, roles и sessions;
- tenant isolation, несколько компаний, company/wallet permissions;
- месячная и годовая подписка ЮKassa, paid company slots, expiry и renewal;
- CSV/XLSX imports, column mapping, банковский ClientBank adapter;
- один согласованный шаблон 1С, загрузка из выделенной почты;
- ручные операции, Telegram-ввод, revisions и audit;
- rules classification, unclassified queue, dedup review;
- cash balances, restricted funds, ДДС, отдельные RevenueEntry;
- календарь, recurrence, обязательства, partial payment matches;
- 91-day daily cash forecast, company/group risk, reserve;
- бюджеты cash/revenue, plan-fact и версии;
- deterministic anomalies/alerts;
- ежедневные Telegram digests и срочные critical notifications;
- web drill-down, source freshness и reconciliation;
- test suite, Compose, backup/restore, demo, эксплуатационные инструкции.

### 1.2. После beta
- свободный AI-чат, голос/OCR, AI-classification;
- прямые bank/CRM APIs;
- полный accrual P&L, сложная consolidation внутригрупповой выручки;
- multicurrency, платёжные согласования, Mini App;
- добровольные автоматические списания.
Нельзя выдавать mock/неподдерживаемый источник за рабочую интеграцию.

## 2. Архитектура, стек и репозиторий

Модульный монолит; отдельные api, workers и единственный beat. Один VPS для пилота, без микросервисов.
Backend: Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 synchronous + psycopg, Alembic, PostgreSQL 16, Redis 7, Celery 5, aiogram 3, openpyxl/csv, pytest/Ruff.
Frontend: React 18, TypeScript, Vite, Tailwind, shadcn/ui, Recharts, TanStack Query, React Hook Form/Zod, Vitest/Playwright.
Deploy: Docker Compose proxy/frontend/api/worker/beat/postgres/redis; Caddy HTTPS; наружу только proxy. Lockfiles и закреплённые версии, production images без latest.

Деньги: Decimal в Python, NUMERIC(20,2) в PostgreSQL, amounts strings в API. Проценты NUMERIC(12,6). PostgreSQL numeric предназначен для точных расчётов, в том числе денег. [web:9]
Float запрещён в финансовом ядре. Number допустим для графической визуализации, но не для денежных итогов.
Все расчёты backend. Web/Telegram читают одинаковые services. Billing продавца и финансовый контур клиента разделены.

Структура:
/backend/app/{api,domain,services,repositories,models,integrations,jobs,security,observability}/
/backend/alembic/
/backend/tests/{unit,integration}/
/frontend/src/{app,pages,features,entities,shared}/
/frontend/tests/
/infra/
/fixtures/
/docs/{architecture,data-model,accounting-policy,api,billing-policy,runbook,acceptance,limitations,decision-log}.md
/.cursor/rules/

Services не импортируют HTTP/bot handlers. External API/IMAP calls не выполняются внутри длительных финансовых DB transactions. Raw файлы вне public web root.

## 3. Рабочие пространства, роли, email-auth

Tenant — рабочее пространство клиента; Company — фирма/ИП в нём. Подписка относится к Tenant.

Роли:
- owner: бизнес-настройки, финансы, пользователи, billing;
- finance_manager: операции/бюджеты/план/прогноз/алерты;
- accountant: imports, classification, документы/сверка;
- viewer: чтение разрешённых компаний, личная подписка на digest;
- operator: ввод по разрешённым кошелькам без общей аналитики;
- billing_manager: специальное право оплаты без автоматического доступа к финансовым операциям.
CompanyAccess ограничивает firms; WalletAccess дополнительно ограничивает operator. Infrastructure admin не получает финансы через UI автоматически; break-glass процедура отдельно с аудитом.
Каждый request/job/callback/send проверяет scope. IDs клиента не доверены. Группа строится только по разрешённым и включённым фирмам. Утрата прав отменяет queued sends.

### 3.1. Регистрация и onboarding
Email/password/name → verify email → login → tenant → draft firm → тариф/число фирм → оферта → ЮKassa → verified succeeded → activation → imports → optional Telegram.
Email trim + case-insensitive политика продукта, UNIQUE normalized_email; не удалять точки/plus tags по gmail-specific правилам.
Password >=12 символов, paste/managers допустимы, Argon2id; без навязанной периодической смены. Rate limit на register/login/reset/resend.
До email verification доступны ограниченный onboarding/resend/logout; production checkout и финансы закрыты.
Приглашённый сотрудник присоединяется к оплаченному tenant, не приобретает дубль подписки.

### 3.2. Email tokens, восстановление и sessions
Случайные одноразовые токены, hash в БД, атомарное consumption: verify TTL24h, reset TTL30min, invite TTL48h.
Register/forgot ответы не раскрывают существование чужого email.
Reset меняет password_hash, отзывает старые sessions и другие reset tokens, отправляет уведомление.
Email change: reauth, подтверждение новой почты, notification старой. Login email и billing_email могут различаться.
Opaque server session ID, HttpOnly/Secure production/SameSite=Lax cookies, CSRF для cookie-auth mutations, idle/absolute timeout configurable. Никаких токенов в localStorage.
Blocked user не входит при active subscription. Expired subscription не запрещает login/renewal.
Письма через TransactionalEmailOutbox и SMTP/provider adapter: verify/reset/invite/payment success/reminders/expiry. Marketing consent отдельно.
URLs только из trusted PUBLIC_BASE_URL. Токены/полные линки не логировать; token pages без сторонней аналитики/Referer leakage.

## 4. Схема данных: общие правила и справочники

UUID PK, timestamptz UTC для технического времени, business_date DATE. tenant_id обязателен, company_id для данных фирмы. Composite FK/constraints не позволяют cross-tenant/company refs. Исторические snapshots immutable.

Организация:
Tenant(id,name,default_timezone,created_at).
User(id,email,normalized_email,password_hash,email_verified_at,status,password_changed_at,created_at).
Membership(id,tenant_id,user_id,role,status).
Company(id,tenant_id,name,legal_name,inn,kind,currency=RUB,timezone=Europe/Moscow,status,min_cash_reserve).
CompanyAccess(tenant_id,user_id,company_id,role_override).
Wallet(id,tenant_id,company_id,name,type,masked_identifier,currency,availability_type,available_from,is_active,minimum_reserve).
WalletAccess(user_id,wallet_id,can_create,can_read).
Direction(id,tenant_id,company_id,name,status).
Counterparty(id,tenant_id,company_id,name,inn,is_related_party,related_company_id).
CashCategory(id,tenant_id,code,name,parent_id,cash_flow_section,direction,exclude_from_operating_metrics).
CompanyCategoryMap(company_id,source_category,canonical_category_id).

Wallet types bank/cash/business_owner_card/deposit/other. Карта собственника отражает только включённые бизнес-деньги, не весь личный баланс. Restricted deposit не доступен до available_from.
Company ИНН уникален среди активных в tenant; несколько кошельков/направлений не создают дополнительную фирму.

## 5. Фактические операции, продажи и остатки

CashTransaction:
id,tenant_id,company_id,wallet_id,business_date,occurred_at nullable,direction(in/out),amount,currency,category_id nullable,business_direction_id nullable,counterparty_id nullable,description,document_number,source(manual/import/telegram),source_connection_id nullable,external_id nullable,import_batch_id nullable,raw_row_id nullable,status(draft/posted/void),classification_origin(rule/manual/none),classification_rule_id nullable,locked_classification,transfer_group_id nullable,related_company_id nullable,created_by,version,created_at,updated_at.
Только posted влияет на расчёты. Сумма positive; знак из direction. posted changes сохраняют revision/audit. Void вместо физического удаления. Optimistic locking version, conflict409.

CashAllocation(transaction_id,category_id,direction_id,amount). Сумма allocations строго transaction.amount; отчёты используют allocations или fallback transaction.category, но не оба слоя одновременно.
TransactionRevision хранит previous significant values.
TransferGroup(id,tenant_id,kind(internal/intercompany),status,pairing_method,confirmed_by): paired legs одной валюты/суммы, комиссия отдельной операцией.

OpeningBalance(id,tenant_id,company_id,wallet_id,effective_at,amount,status): один активный anchor на wallet, остаток непосредственно перед effective_at.
BalanceSnapshot(id,wallet_id,as_of,amount,source_connection_id,import_batch_id,coverage_through).
Reconciliation(id,wallet_id,as_of,computed_balance,source_balance,difference,status,resolved_by,comment).
Snapshot не подменяет вычисленный баланс автоматически. Adjustment при согласованном устранении расхождения — отдельная technical posted operation.

RevenueEntry:
id,tenant_id,company_id,business_direction_id,counterparty_id,recognition_date,document_date,document_number,external_id,source_connection_id,amount_ex_vat,vat_amount,amount_inc_vat,entry_type(sale/return),status,import_batch_id.
RevenueCashMatch(revenue_entry_id,cash_transaction_id,amount) — справочная связь оплаты/продажи, не источник признания.
Выручка по policy и sales documents. Cash receipts/advance/loan/owner contribution/internal transfer не создают sale автоматически.

## 6. План, обязательства, бюджеты и расчётные runs

PlannedCashEvent:
id,tenant_id,company_id,wallet_id nullable,direction,amount,currency,category_id,counterparty_id,business_direction_id,due_date,expected_date,confidence(confirmed/expected/tentative),priority(critical/high/normal/low),status(planned/partially_paid/paid/cancelled),recurrence_rule_id,occurrence_key,notes,version.
PaymentMatch(id,event_id,transaction_id,allocated_amount,created_by).
RecurrenceRule(id,company_id,template,frequency,interval,day_of_month,start_date,end_date,month_end_policy).
Obligation(id,company_id,type(receivable/payable),counterparty_id,document_ref,issue_date,due_date,original_amount,status).
ObligationCashLink(obligation_id,event_id): один экономический долг формирует один residual forecast event, не второй дубликат.

BudgetVersion(id,tenant_id,company_id,name,year,status(draft/approved/archived),basis(cash/revenue),approved_at).
BudgetLine(id,budget_version_id,month,category_id nullable,direction_id nullable,metric_type(cash_in/cash_out/revenue),amount,distribution_method(calendar_days/business_days/custom)).
BudgetDailyAllocation(line_id,date,amount) для custom.
Calendar_days обязателен в beta; остальные только при реальной реализации/тестах. Одна approved версия company/year/basis; её изменение создаёт новую.

ForecastRun(id,tenant_id,company_id,as_of,coverage_cutoff,scenario,horizon_days,input_revision,status,quality_flags,created_at).
ForecastPoint(run_id,date,wallet_id nullable,opening,inflows,outflows,closing,reserve,headroom).
ForecastContribution(run_id,date,source_type,source_id,amount,direction,assumption).

## 7. Импорт, подключения, сигналы и уведомления: модели

SourceConnection(id,tenant_id,company_id,type,name,config_redacted,encrypted_credentials,enabled,poll_interval,last_attempt_at,last_success_at,data_coverage_through,status).
ImportProfile(id,connection_id,format,encoding,sheet_name,column_mapping,date_format,decimal_separator,sign_policy,schema_version).
ImportBatch(id,tenant_id,company_id,connection_id,file_hash,file_storage_key,status,rows_total,rows_valid,rows_invalid,rows_committed,created_at,completed_at).
RawImportRow(id,batch_id,row_number,raw_payload,normalized_payload,validation_errors,duplicate_status,proposed_action).
SourceIdentity(id,company_id,source_connection_id,entity_type,external_id,canonical_entity_id,payload_hash).
EmailIngestion(id,connection_id,uidvalidity,uid,message_id,attachment_hash,status,batch_id).
ClassificationRule(id,tenant_id,company_id nullable,priority,conditions_json,actions_json,enabled,version).

AlertRule(id,company_id,type,thresholds_json,severity,enabled,cooldown_minutes).
Alert(id,tenant_id,company_id,type,fingerprint,severity,status(open/acknowledged/resolved),first_seen_at,last_seen_at,evidence_json,source_refs,resolved_at).
TelegramBinding(id,user_id,tenant_id,telegram_user_id BIGINT,chat_id BIGINT,status,linked_at,revoked_at).
TelegramLinkToken(id,user_id,tenant_id,token_hash,expires_at,used_at).
DigestSubscription(id,user_id,tenant_id,binding_id,company_scope,local_time,timezone,days_of_week,mode(group/per_company/both),enabled,instant_alerts,quiet_hours,privacy_level,last_scheduled_for).
DigestSnapshot(id,subscription_id,local_date,scheduled_for_utc,as_of,company_ids,metrics_json,quality_json,content_hash,status).
NotificationOutbox(id,snapshot_id nullable,alert_id nullable,binding_id,part_number,payload,status(pending/sending/sent/retry/failed/unknown/cancelled),attempts,next_attempt_at,telegram_message_id,last_error,lease_until).
TelegramUpdate(bot_id,update_id,payload_hash,received_at,status).
BotDraft(id,binding_id,state,payload,expires_at,idempotency_key).
VerificationToken(id,user_id,token_hash,purpose,expires_at,used_at).
TransactionalEmailOutbox(type,to,template_key,payload_redacted,idempotency_key,status,attempts,next_attempt_at).
AuditLog(id,tenant_id,user_id,action,entity_type,entity_id,before_redacted,after_redacted,request_id,created_at).

Уникальные ключи: SourceIdentity namespace/external_id; connection/uidvalidity/uid/attachment_hash; recurrence occurrence_key; bot/update_id; subscription/local_date scheduled snapshot; snapshot/binding/part_number outbox.
Индексы: tenant/company/business_date, wallet/date/status, alert/company/status, event/company/expected_date, outbox/status/next_attempt_at.

## 8. Финансовая методология: обязательные инварианты

### 8.1. Балансы и ликвидность
Balance(wallet,t) = anchor + posted incoming − posted outgoing от effective_at до t.
Операции ранее anchor не влияют на subsequent balance. Нет anchor → unavailable, не 0.
Business_date-only даёт конец дня; intraday approximation маркируется.
Общий cash = все кошельки управленческого периметра.
Available cash = spendable кошельки, restricted исключены до availability date.
Headroom = available − reserve. Резерв не вычитать второй раз.
Source snapshots для сверки, не silent override.

### 8.2. ДДС, переводы и группа
Cash categories: operating/investing/financing/technical.
Внешние posted потоки меняют cash; loans/owner funds — financing, не revenue.
Внутренний wallet transfer меняет balances, но исключён из external turnover компании.
Intercompany transfer отражается в каждой фирме; в выбранной группе обе подтверждённые ноги исключаются из external turnover, только если обе фирмы внутри scope. Нет pairing или одна фирма вне scope → не исключать.
Positive group cash не означает свободную взаимозаменяемость денег юридических лиц. Company-specific gap показывается даже при positive group total.
Restricted deposit transfer внутри компании не external cash-in/out, но меняет available cash.
Customer refund: cash effect по выплате, sales return по recognition_date.
Canonical category mapping для group; unmapped остаются отдельной группой, не исчезают.

### 8.3. Выручка, НДС и прибыль
Revenue = posted sales ex_vat − returns ex_vat по recognition_date.
Нет подключённых sales → null/unavailable, не 0 и не cash-in.
Если full reliable sales coverage есть и продаж не было → 0 допустим.
Если VAT basis неизвестен, label «сумма продаж по данным источника», flag vat_basis_unknown; не выдавать за net revenue.
Group sales sum подписывать «сумма выручки фирм до исключения внутригрупповых продаж» до полноценной revenue consolidation.
Cash-in − cash-out называется чистым денежным потоком, не прибылью. Accrual P&L вне beta.

### 8.4. План/факт и residual amounts
Remaining event = amount − matches по posted transactions. Nonnegative; currency/company/direction согласованы; sum allocations не превышает transaction amount.
Paid часть уже в фактическом cash, в forecast только остаток.
Void связанного факта восстанавливает residual после recalculation.
Ambiguous auto-match только предложение, подтверждается человеком.
Budget не создаёт forecast event автоматически. Нельзя считать один платёж трижды из budget/event/obligation.

## 9. Импорт и 1С/почта

### 9.1. Published file contracts
cash_transactions.csv: external_id,wallet_code,business_date,direction,amount,currency,counterparty_inn,counterparty_name,description,document_number,category_code,direction_code.
revenue.csv: external_id,recognition_date,document_number,counterparty_inn,amount_ex_vat,vat_amount,amount_inc_vat,entry_type,direction_code.
planned_cash.csv: external_id,direction,amount,currency,due_date,expected_date,category_code,counterparty_inn,confidence,priority,wallet_code.
budget.csv: year,month,basis,metric_type,category_code,direction_code,amount,distribution_method.
balances.csv: wallet_code,as_of,balance,currency.
Document mandatory fields/enums, YYYY-MM-DD, decimals/encoding and real fixtures. XLSX values only, no macro execution; obligatory money formula without cached value rejected.
ClientBankExchange — отдельный проверенный parser. Не заявлять универсальное чтение произвольных отчётов 1С.

### 9.2. Pipeline
received → validating → preview_ready → committing → completed/completed_with_errors/failed.
Проверка type/size/hash → raw rows → normalize → scope/date/currency validate → dedup/change detection → preview → commit → classification → invalidate reports/forecast/alerts.
Preview counts: new/repeated/changed/invalid/ambiguous. Ошибки с row numbers, скачиваемый отчёт.
Column mapper сохраняет profile. Default limit20MB,100000 rows, decompressed XLSX/time limits configurable.
CSV export экранирует формульные начала =,+,-,@ в text fields.

### 9.3. Дедупликация
- повтор файла не создаёт новых canonical transactions;
- external_id в logical source namespace identifies entity;
- changed payload same id → revision proposal, не duplicate;
- fingerprint date/amount/description лишь candidate, не доказательство;
- legit одинаковые платежи с разными IDs остаются отдельными;
- банк/1С одного payment → одна canonical transaction, несколько SourceIdentity;
- ambiguous cross-source candidate в review, не posted;
- authoritative cash source для каждого wallet; secondary enriches classification/docs, не дублирует cash;
- DB constraints/locks для parallel imports;
- manual locked classification не перезаписывать.

### 9.4. IMAP и формат 1С
Выделенная почта, IMAP TLS, provider OAuth/app-password adapter. Credentials encrypted separate env key.
Filters sender/subject/folder/type/profile/company mapping. Company определяется config, не только filename. Sender filter не authentication; insecure channel → preview, не auto-post.
Poll default30min; UIDVALIDITY/UID + attachment hash, письма не удалять, Message-ID не единственный key.
Trusted auto-import только validated schema/scope/reconciliation; format changes требуют review.
last_success после commit; data_coverage_through — реальный покрытый период, не receive timestamp. Valid empty export может подтвердить coverage без transactions.
Документировать spec для 1С-разработчика и список реально поддержанных configurations/exports. Integration unknown → явное unsupported.

## 10. Классификация

Conditions: counterparty INN, description contains/equals, direction,wallet,source,amount range; regex вне beta.
Actions: category,direction,related party flag. Transfer pairing — отдельное подтверждаемое действие.
Priority: manual locked → company rule → tenant rule → unclassified; first match, tie по stable ID, warning conflict.
Evidence: rule/version/conditions. Bulk apply/reclassify с preview и подтверждением. Amount/date/wallet не меняются.
Unclassified включены в balance/cash totals, но снижают completeness категории/budget.

## 11. Платёжный календарь и forecast

Views day/week/month/list. Event: firm,date,due date,amount/paid/remaining,category,wallet,priority,confidence.
expected_date move не меняет due_date, не скрывает overdue.
Recurring weekly/monthly, day29–31 last-day default; transactional idempotent occurrence generation до horizon.
Выходные не переносить без настроенного business calendar.
Overdue payables conservative ближайший forecast day; overdue receivables не confirmed без нового expectation. Просрочка отдельным сигналом.

Forecast horizon91 calendar days=13 weeks, 7/14/30/90 slicers.
Closing(d)=Opening(d)+RemainingInflows(d)−RemainingOutflows(d).
Opening(next)=Closing(previous).
Forecast — конец дня, не intraday guarantee. Старт usable cash as_of; same-day remaining events после cutoff, paid facts не повторять.
Restricted funds становятся available по явной дате; no invented external revenue.
Input revision в run; fact/matches/plans invalidate old run. Contributions и assumptions раскрываемы.

Scenarios:
Base: confirmed/expected inflows, planned payouts; tentative inflows excluded.
Conservative: expected inflows default delay7days и80% residual, confirmed без haircut, расходы без уменьшения.
Optimistic: base+explicit tentative inflows, без invented growth.
Category confidence не probability. Автоэкстраполяция выручки disabled в beta.

Risks:
- cash_gap: earliest closing<0, amount=max(0,−minimum closing);
- reserve_breach: nonnegative closing<reserve, shortage=reserve−closing;
- wallet_gap: недостаток назначенного wallet, без automatic transfers;
- missing anchor → unavailable;
- incomplete input → preliminary, не «рисков нет».
Group показывает company-specific gaps и scope completeness.

## 12. Бюджеты, отклонения и аномалии

Budget cash сравнивается с cash fact; revenue budget с RevenueEntry. Basis не взаимозаменяемы.
Plan_to_date = daily allocations с начала месяца по report_date.
Calendar_days равномерно, remaining rounding cents последнему дню, sum exactly month plan.
Delta=fact−plan_to_date.
Percent=delta/abs(plan_to_date)×100 при plan!=0.
plan0/fact0→percent0; plan0/fact!=0→percent null, «вне бюджета».
Expense growth adverse; revenue shortfall adverse; loan inflow excess не автоматически favorable.
Missing approved budget → unavailable, deviation alert не генерируется.
No partial fact vs full monthly plan как состоявшееся отклонение. Period,basis,version,scope,coverage показаны.

Начальные configurable alert rules (не универсальные бизнес-нормы):
1 cash_gap на7/14/30/90 дней.
2 reserve_breach.
3 expense budget overrun >=50000 RUB и>=15%.
4 revenue shortfall>=50000 и<=−15% при reliable comparable data.
5 single external outgoing>=300000.
6 unusual outgoing>=50000 и>3×median той же категории за предшествующие90days; baseline>=10, current excluded.
7 new counterparty first outgoing>=100000.
8 duplicate candidate → warning review.
9 stale source default24h expected coverage lag, учитывается schedule/выходные.
10 reconciliation abs(diff)>configurable1 RUB.
11 overdue receivable/payable residual>0 иdue_date<report_date.
12 unclassified external out share>10%; denominator0→null.
Insufficient baseline → insufficient_history, не фиктивный statistical alert.
Anomaly не доказательство мошенничества.

Alert evidence: numbers/formula/threshold/period/source refs/quality. Stable fingerprint по firm/type/risk object.
Lifecycle open→acknowledged→resolved; ack не устранение.
Repeated calculation updates same alert. Urgent resend только severity/materiality worsening default20%, cooldown6h. Open signals в daily digest.
Poor quality не подавляет доказанный риск, но запрещает уверенное all-clear.

## 13. Telegram: привязка, команды и ввод

Только private chats в beta, группы/каналы запрещены.
Binding: authenticated web→random token(hash,TTL10min)→deep link→bot receives telegram user/chat IDs→atomic token consumption→pending→web confirmation→active.
Telegram deep link start parameter до64 chars, token base64url без финансов/прав. [web:8]
Не привязывать по username/phone/client chat_id. Один active binding user/tenant; контекст tenant explicit.
Real finance только verified email + active subscription + rights + active binding.
Unlink или /stop отключает subscriptions и pending outbox. Callback повторно проверяет актуальные права и scope.

Команды:
/start safe menu/binding; /help; /companies scope;
/summary свежая сводка; /balance; /forecast; /revenue; /budget; /alerts; /sources;
/add input wizard; /settings; /stop.
Callback data opaque reference, без sensitive payload; answerCallbackQuery после обработки.

/add: company→in/out→wallet→amount→local date→category→optional direction→comment→preview→confirm/cancel.
«Это запись учёта, не банковский платёж». Decimal with spaces/comma, default local day, unclassified allowed.
Draft TTL30min, confirm idempotency key. Cash/manual wallets may posted; authoritative bank wallet → pending/draft до reconciliation, чтобы не удвоить imported payment.
Free text/OCR/voice не обязательны. LLM не угадывает amount без подтверждения.

## 14. Telegram: дайджест и расписание

Default daily08:30 Europe/Moscow; timezone IANA,time,days,scope,group/per_company/both configurable.
Report date вчера в timezone subscription. Отдельные cutoffs:
- balances по actual as_of/coverage;
- yesterday flows/sales по report_date;
- MTD до report_date;
- forecast от пригодного cash cutoff.

Beat каждую минуту ищет due, DB lock creates one snapshot/local_date и outbox. Beat не send напрямую.
DST nonexistent time→next valid; repeated time→one scheduled message. Restart не дублирует.
Catch-up default<=2h; no backlog morning spam.
Source wait max30min then send stale warning/date, не fictitious zeros. IMAP не блокирует всё indefinitely.
Snapshot фиксирует revision/values, all message parts one version. Manual /summary отдельный request_id.
Перед enqueue иsend проверяются subscription/rights.

Порядок сводки:
1 дата, scope, актуальность;
2 critical gap/date/amount;
3 total/available/restricted/reserve;
4 yesterday incoming/outgoing/net cash;
5 revenue yesterday/MTD или unavailable;
6 budget MTD delta amount/%/basis;
7 upcoming7days/overdue;
8 top3 anomalies;
9 freshness/reconcile/unclassified;
10 inline buttons firms/calendar/forecast/web.
Many firms→group executive summary+risky company list+compact cards; partial group aggregate явно подписан.
Privacy compact hides counterparties/purposes, amounts ranges optional; full opt-in.
protect_content=true дополнительная мера, не обещание защиты от screenshots. Web URL без session token, обычная auth.

Шаблон, цифры синтетические:
«Сводка за 13 октября. 2 фирмы. Данные по 13.10 23:59, сформировано14.10 08:30 МСК.
Внимание: ООО Альфа 18 октября — расчётный дефицит180000 ₽.
Деньги всего3420000 ₽, доступны2920000 ₽, restricted deposit500000 ₽.
Вчера incoming640000 ₽, outgoing510000 ₽, net+130000 ₽.
Revenue net MTD4100000 ₽ — сумма фирм до исключения внутригрупповых продаж.
Альфа: cash expenses1400000 ₽ при план-к-дате1200000 ₽, +16,7%.
Выплаты7days1150000 ₽. Проверить: первый counterparty payment320000 ₽.
Бета: bank coverage только12 октября, group estimate preliminary.»

## 15. Telegram transport и надёжность

Production HTTPS webhook + проверка X-Telegram-Bot-Api-Secret-Token. Development long polling, не одновременно; Bot API описывает secret header и взаимоисключающие способы получения updates. [web:10]
Webhook200 после durable update save; worker processing, unique update_id.
sendMessage max4096 chars after parsing; project limit3500 per part, split by semantic blocks, escape HTML/user fields, не разрывать entities. [web:10]
429 retry_after;5xx/transient exponential backoff+jitter;403 binding disabled/cancel queue;400 formatting failed, no infinite retries.
Rate limit configurable starting20msg/sec bot,1/sec chat, no guarantee provider maxima. Per chat ordering.
API accepted ≠ read by owner.
Exactly-once Telegram delivery не обещать: request sent,response lost→unknown, не blind resend. Multipart tracks parts, sent parts не повторяются; operator resend с предупреждением.
Без token app работает, integration disabled. Default SEND_EXTERNAL_MESSAGES=false; test mock transport, real smoke только после разрешения.

## 16. Подписка: месячный и годовой тариф

Тариф beta:
MonthlyPrice(N)=2500.00+1500.00×(N−1), N>=1.
AnnualListPrice=MonthlyPrice×12.
Approved annual discount=15.00%.
AnnualPayable=ROUND_HALF_UP(AnnualListPrice×0.85,2).
Savings=List−Payable; monthly equivalent=AnnualPayable/12, справочно.
N0→no paid real finance, min paid configuration1firm.
Скидка на весь набор фирм, не только первую. Actual annual charge единовременно, не monthly equivalent.

| Фирмы | Месяц | 12 месяцев без скидки | Год, скидка 15% | Экономия | Эквивалент/месяц |
|---|---:|---:|---:|---:|---:|
| 1 | 2 500 ₽ | 30 000 ₽ | 25 500 ₽ | 4 500 ₽ | 2 125 ₽ |
| 2 | 4 000 ₽ | 48 000 ₽ | 40 800 ₽ | 7 200 ₽ | 3 400 ₽ |
| 3 | 5 500 ₽ | 66 000 ₽ | 56 100 ₽ | 9 900 ₽ | 4 675 ₽ |
| 4 | 7 000 ₽ | 84 000 ₽ | 71 400 ₽ | 12 600 ₽ | 5 950 ₽ |
| 5 | 8 500 ₽ | 102 000 ₽ | 86 700 ₽ | 15 300 ₽ | 7 225 ₽ |

2500/1500 — конечные суммы для клиента; эквайринговая комиссия не сверху. Налоговые attributes отдельно согласно продавцу, VAT не выдумывать.
Дополнительные users/wallets/directions/Telegram без отдельной платы beta; сохраняются technical limits. ИП как1firm. No automatic free trial/onboarding fee/year autocharge.
Синтетический demo отдельно без real integrations.
Subscription tenant-level, company_limit+explicit entitlements. Company draft до оплаты. Не начислять сотруднику отдельную плату за те же firm data.
TariffVersion immutable snapshots; price change не пересчитывает оплаченный срок.
AnnualOfferVersion approved15%, approved_at=14.10.2026, approval_source=user; статус approved, не оставлять live блокировку «скидка не утверждена». Live rollout всё равно требует offer/tax/credentials readiness.

### 16.1. UI тарифа
Toggle Month/Year, обе цены server-driven. Для year:15%,list,total savings,equivalent per month,N,start/end; CTA «Оплатить год — <полная сумма> ₽».
Клиент видит beta status/срок/добавление и уменьшение фирм до оплаты. Оферта version иinterval сохраняются.
No stacking discounts/promocodes без отдельного требования.
Screen «Тариф и оплата»: active/paid slots, dates,status,change count,quote,renewal,invoice/payment/refund/receipt history,billing email,payer details,offer/cancel terms.

## 17. Периоды, изменения подписки и оплаченный доступ

Billing intervals month|year; period[start,end), calendar month/12months from anchor, timezone Europe/Moscow default, UTC stored. Не фиксированные30/365days.
First starts provider confirmed succeeded_at. Month-end policy last valid day; original anchor сохранён, Feb29→Feb28 non-leap without subsequent drift.
Early renewal next start=current end, late starts confirmed payment unless separately agreed debt policy.
Cancel renewal не прерывает current paid access.
Current иfuture prepaid periods отдельно: оплата будущего года не меняет current company count немедленно.

### 17.1. Switch month/year
Beta defaults:
month→year starts after current monthly end; prepay allowed.
year→month after paid annual end.
Immediate credit/refund conversion outside beta, support/manual review.
No overlapping periods from double click; lock/revision/unique activation.
Если число firm меняется после покупки future period, нужен revised quote/reconciliation; не silently reprice purchased period и не терять полученные средства.

### 17.2. Upgrade/Downgrade
Monthly upgrade=ROUND_HALF_UP(1500×added_slots×remaining_seconds/period_seconds,2).
Annual additional full-period price=1500×12×0.85=15300.00 RUB.
Annual upgrade=ROUND_HALF_UP(15300×added_slots×remaining_seconds/period_seconds,2).
Берётся discount snapshot current paid period, не новая global config. При exactly half remaining annual additional=7650 RUB.
Quote TTL15min, фиксирует revision/as_of/amount. After verified success places until unchanged period_end, next renewal full updated N.
Quote<1RUB→offer next period start, no zero payment.
Late upgrade after current end→manual review, not unpaid new term activation.
Decrease next period, choose firms to keep. No auto partial refund; valid contractual/legal cases separate procedure.
Archive не пересчитывает paid fee. Замена активного ИНН черезsupport/audit, чтобы нельзя было обработать unlimited firms одним местом. Names editable.

### 17.3. Lifecycle и ограничения
States awaiting_payment/active/grace/expired/cancelled; cancellation renewal flag отдельно от paid entitlement.
Grace по умолчанию 3 календарных дня: read-only/export. Immediately after paid_through stop writes/import/forecast regeneration/financial Telegram.
After grace login/billing/profile/export request/delete request, financial screens blocked. No auto financial data deletion.
Applicable data access rights реализуются по согласованной policy, не блокируются неоплатой механически.
Guard auth+verified email+membership+RBAC+company entitlement+time. В API/jobs/callback/outbox send, paid_through проверять даже если expiry task не отработал.
Billing всегда доступен billing-permitted user для renew. Queue financial sends cancelled at expiry; billing reminders separately opt-in no cash/revenue.
Read-only stale forecast не обозначается fresh.

## 18. Billing models и ЮKassa

TariffVersion(id,code=beta,version,currency=RUB,monthly_first_company_price=2500,monthly_additional_price=1500,valid_from/to,status,tax_config_version).
AnnualOfferVersion(id,tariff_version_id,discount_percent=15,status=approved,approved_by,approved_at,offer_terms_version,valid_from/to).
BillingAccount(id,tenant_id,payer_type,payer_name,inn,billing_email,offer_version,offer_accepted_at,consent_versions).
Subscription(id,tenant_id,tariff_version_id,status,company_limit,current_interval,scheduled_interval,paid_through,billing_anchor,timezone,auto_renew=false,scheduled_company_limit,revision).
CompanyEntitlement(id,subscription_id,company_id,active_from,active_until,status,period_id).
BillingPeriod(id,subscription_id,start_at,end_at,interval,company_limit,monthly_base_snapshot,discount_percent,annual_offer_version_id,paid_amount,status,activation_invoice_id).
BillingQuote(id,subscription_id,kind(initial/renewal/upgrade),interval,as_of,expires_at,expected_revision,target_company_limit,list_amount,discount_amount,payable_amount,discount_percent,offer_version,period_start/end,calculation_json).
Invoice(id,tenant_id,subscription_id,quote_id,kind,status(draft/pending/paid/cancelled/manual_review),number,currency,list_amount,discount_amount,payable_amount,pricing_snapshot,billing_interval,intended_period_start/end,paid_at).
InvoiceLine(id,invoice_id,description,quantity,discounted_unit_price,amount,company_refs,service_period_start/end,receipt_attributes).
PaymentAttempt(id,invoice_id,provider=yookassa,provider_payment_id UNIQUE nullable,idempotence_key UNIQUE,request_hash,amount,currency,status(new/pending/waiting_for_capture/succeeded/canceled/unknown),test_mode,confirmation_url,created_at,verified_at,provider_error).
BillingWebhookInbox(id,provider,object_id,event,payload_hash,payload_redacted,received_at,status,attempts,last_error).
BillingActivation(id,invoice_id UNIQUE,subscription_id,period_id nullable,change_revision,applied_at).
Refund(id,payment_attempt_id,provider_refund_id UNIQUE nullable,amount,status,idempotence_key,reason,created_by,verified_at).
BillingAudit(id,tenant_id,actor,action,entity_id,evidence_redacted,created_at).

Billing продавца не создаёт автоматически CashTransaction/RevenueEntry клиента. Credentials shop принадлежат SaaS, не клиентским firms; frontend не может подменять shop_id.

### 18.1. Платёжный сценарий
1 Verified email + billing permission выбираетN/interval, server quote.
2 Accept versioned offer, immutable invoice/payment attempt.
3 Server create ЮKassa payment amount RUB,capture=true,redirect confirmation,description,metadata invoice/subscription/tenant/interval,receipt.
4 Hosted checkout, PAN/CVV не на сервере SaaS.
5 Return URL показывает pending verification, не grants access.
6 Webhook durable inbox→worker GET actual payment provider API.
7 Verify local ID/status succeeded/amount/currency/shop/environment/test/metadata.
8 Atomic DB lock apply paid invoice/one activation/period/entitlements.
9 Email/receipt notification outbox, email failure не отменяет successful payment.
10 Reconciliation pending/unknown restores missed webhook, no extra charge.

Webhook events payment.succeeded/payment.canceled/refund.succeeded, подтверждение200 и проверка актуального объекта/IP описаны ЮKassa. [web:31]
GET verification перед activation обязателен, IP allowlist дополнительно актуальный provider list; trusted proxy, no untrusted forwarded headers. Не выдумывать HMAC header отсутствующий в схеме.
Webhook no cookie/CSRF auth, но provider checks,size/rate limits.200 после durable valid save, processing async. Не активировать неизвестные объекты и не откатывать конечный статус старыми событиями.
Provider unavailable→retry без непроверенного granting.
Create/refund stable Idempotence-Key+same payload; timeout не значит создать новый charge. После provider idempotency window reconcile/manual review, не blind repeats. [web:24]
Test=true never activates live tenant. Real operations only explicit enablement.
Annual payment one full discounted amount; metadata intervalyear иdescriptionservice period. Receipt lines discounted sum exactly total, no unsupported negative discount line.

### 18.2. Продление, уведомления, refunds
Manual renewal обязательный beta. Month напоминания за 3/1/0 дней; год: за 30/7/1 дней configurable opt-in. No autocharge.
Optional later auto-renew: explicit consent/off,save_payment_method=true supported scenario,saved flag verified,provider payment_method_id only,no silent price increases,finite retries. Согласие и сохранение способа описаны ЮKassa. [web:27]
Refund только authorized SaaS seller staff с явным подтверждением, не arbitrary client endpoint. API/webhook synchronize. Full activation refund→correct/revoke paid period поapproved policy; partial manual review; данные не стирать.
Права/основания возврата согласуются отдельно, не заменяются техническим default «no auto refund».

### 18.3. Фискализация и production readiness
Seller legal form/tax/VAT/receipt applicability/provider и аванс/зачёт scenario уточнить до real checkout. No arbitrary VAT rate.
Receipt email/buyer fields/subject/mode/lines согласно agreed setup; invoice line sum equals payment amount.
Email-квитанция не автоматически фискальный чек; ЮKassa разграничивает их и использует email в решении «Чеки от ЮKassa». [web:26][web:25]
Mandatory receipt config missing→live checkout blocked. Внешний compliance review до commercial launch, не заявление гарантированного соответствия.

## 19. Web UX и API

Навигация: Обзор/Операции/Кошельки/Продажи/Календарь/Прогноз/Бюджеты/Алерты/Импорт/Справочники/Тариф и оплата/Настройки.
Global tenant/company/group selector,dates,direction,freshness,last calculated.
Overview: total/available/restricted/reserve,yesterday/MTD cash,revenue basis,forecast min/earliest gap/company risks,bars/donut/forecast,reserve line,alerts/payments,drilldown.
Transactions: server pagination/filters,allocations,classify,revisions,raw refs,duplicate review,bulk preview.
Wallets: anchors,snapshots,reconciliation,availability.
Sales: net/grossVAT/returns/matches, не cash-in table.
Forecast:91day,scenario,contributions,quality.
Budgets:import/edit/version/approve/plan-factzero handling.
Alerts:evidence/ack/history. Imports:preview/errors/profiles/source health.
Settings:roles/categories/rules/thresholds/IMAP/Telegram/timezone/audit.
Responsive1440/390px,ru-RU,ДД.ММ.ГГГГ,₽. Loading/error/empty/unavailable разные состояния. Цвет не единственный risk signal. No data≠0.
Не копировать branding/name автора/точный дизайн референса.

### 19.1. API v1
Auth: POST /auth/{register,verify-email,resend-verification,login,logout,forgot-password,reset-password,change-email-request,change-email-confirm}; GET /auth/me,/auth/sessions; DELETE /auth/sessions/{id}; POST invitations/accept.
Company: GET/POST /workspaces/{tenant}/companies; GET/PATCH /companies/{id}; GET/POST /companies/{id}/wallets; POST /wallets/{id}/opening-balance; GET reconciliation.
Cash: GET/POST /companies/{id}/transactions; GET/PATCH /transactions/{id}; POST /transactions/{id}/void,classify; POST /transfers/link.
Revenue: GET/POST /companies/{id}/revenue.
Imports: POST /companies/{id}/imports; GET /imports/{id}/preview,errors; POST /imports/{id}/commit.
Rules: GET/POST /companies/{id}/classification-rules; POST /rules/{id}/preview.
Plan: GET/POST /companies/{id}/planned-events; PATCH /planned-events/{id}; POST /payment-matches.
Budget: GET/POST /companies/{id}/budgets; POST /budgets/{id}/approve.
Reports: GET /companies/{id}/{dashboard,cashflow,forecast}; forecast query scenario/days; GET /workspaces/{tenant}/group-summary?company_ids=...
Alerts: GET /companies/{id}/alerts; POST /alerts/{id}/ack.
Sources: GET /companies/{id}/sources; POST /sources/{id}/test,sync.
Telegram: POST /telegram/link-token,/telegram/binding/confirm; DELETE binding; GET/PUT subscription; POST digest-preview/send-test; POST /integrations/telegram/webhook.
Billing: GET /billing/{tariff,subscription,invoices}; POST /billing/{quote,checkout}; GET /billing/payments/{id}; POST /billing/subscription/{schedule-change,cancel-renewal}; POST /billing/companies/{id}/activate; POST /integrations/yookassa/webhook.
Frontend /billing/return не webhook. Health /health/live,/health/ready.

Prefix /api/v1 кромеfrontend/health. Schema/OpenAPI canonical, frontend generated contract.
Errors{code,message,details,request_id};400validation,401auth,402billing,403permission,404invisible,409revision/idempotency,422semantic.
Create cash/match/import commit/billing checkout Idempotency-Key. Same key+payload returns result; changed payload409.
ISO dates,UTC offsettimestamps,stringmoney,pagination<=100.
Report:as_of,coverage_through,input_revision,quality_flags,metric_basis,values,drilldown_refs.
Billing quote acceptsN/interval, never trusted clientprice/discount; GET tariff approved annual15%. Subscription current/future periods явны.

## 20. Качество, безопасность и эксплуатация

Flags:missing_opening_balance,stale_cash_source,partial_period,missing_revenue_source,vat_basis_unknown,unclassified_operations,reconciliation_difference,ambiguous_duplicates,missing_budget,stale_forecast. Per metric/company.
Не all-clear при missing forecast/plans. Group partial explicit.
Metrics:queue age/importduration/errors/coverage lag/reconcile diffs/digest lag/sendfailed/unknown/workerheartbeat/calculation latency/authdenials.
Structured logs request/job/batch IDs, no passwords/tokens/cards/raw attachments/full financial messages by default.
Tenant admin sees source/job/delivery health without infrastructure secrets.

TLS,no exposedDB/Redis,minDB privileges,separatemigration role.
RLS tenant financial tables defence-in-depth, transaction-local tenant setting, pooledconnection contamination tests иworker context.
Secrets encrypted env separatekey,неGit. Login/link/import rate limits,webhook checks/replay dedup.
Audit roles/exports/bindings/changes. Mask wallet identifiers,minimize PII.
Raw attachment retention default90days adjustable; finance/audit retention отдельно согласовать.
Data hosting proposed российский контур; правовые обязательства/Telegram data sharing review до пилота.
Explicit Telegram financial sharing opt-in/privacy. External LLM disabled default, no silent uploads.
Production checkout blocked безseller/receipt/готовности оферты и учётных данных, но annual15% ужеapproved.

Backup encrypted daily pg_dump+attachments внеVPS,14daily+8weekly default. Restore до пилота иmonthly. Targets RPO<=24h,RTO<=4h проверяются restoration, не обещание без процедуры.
Redis не source of truth; DB outbox/tasks recover queue.
Compose не регистрирует webhooks/не делаетcharges/send автоматически. Admin commands иrunbook отдельно сpermission.

ENV minimum:
PUBLIC_BASE_URL
DATABASE_URL/REDIS_URL
SESSION/SECRET_ENCRYPTION_KEY
BOT_TOKEN/TELEGRAM_WEBHOOK_SECRET
SEND_EXTERNAL_MESSAGES=false
BILLING_ENABLED=true
BILLING_MODE=test
YOOKASSA_SHOP_ID/YOOKASSA_SECRET_KEY/YOOKASSA_RETURN_URL
SEND_LIVE_PAYMENTS=false
RECEIPT_MODE
BILLING_GRACE_DAYS=3
ANNUAL_BILLING_ENABLED=true
ANNUAL_DISCOUNT_PERCENT=15.00
ANNUAL_RENEWAL_REMINDER_DAYS=30,7,1
EMAIL_PROVIDER_MODE=mock
SEND_REAL_EMAIL=false
AnnualOfferVersion approval seed15% выполнен, не повторный approvalfalseflag. Config change не изменяет immutablepaidversion.
Billing guard bypass толькоlocaldemo/development, не production. Безcredentials приложение запускается с отключённой интеграцией, no fake success.

## 21. Производительность, демо и deliverables

Pilot load profile4 vCPU / 8 GB RAM / SSD,10 фирм/tenant,20 пользователей,100 000 posted cash transactions/company/year,2 000 прогнозных событий на горизонт,100 подписок на установку. Это design workload, требуется измерение.
Targets warm dashboard p95 < 3 s,bot ack < 2 s,импорт 10 000 строк < 120 s,forecast 91 дней/company < 5 s,старт due digest processing <= 5 min здоровой системы.
Load script ифактические результаты, не «выполнено» безrun. Cache tenant/scope/input_revision, invalidateизменении факта. Digest snapshots неизменяемы.

Demo isolated tenant: ООО Альфа/ИП Бета,5 кошельков / 1 restricted deposit,90 дней cash/sales/budgets,91 день plans,company gap при положительном остатке группы,unclassified,partial payment,bank/1C duplicate,owner funds,return,stale source. Только синтетические данные, без автоматического seed в production.

Deliverables:
- sources/migrations/lockfiles/CI;
- Compose dev/prod/env.example без secrets;
- опубликованные import fixtures и спецификация 1С;
- demo seed/reset;
- tests/loadreport/OpenAPI;
- architecture/ER/accounting/billing policies;
- install/upgrade/backup/restore/rollback runbook;
- Telegram/IMAP/YooKassa/email setup и troubleshooting;
- security/acceptance/limitations/decisionlog;
- offer/taxconfiguration integration readiness checklist, не выдуманные юридические документы.

## 22. Контрольные тесты и автоматизация проверки

Обязательны unit-тесты формул, интеграционные тесты с настоящим PostgreSQL и E2E ключевых пользовательских сценариев. CI запускает линтеры, проверку типов, миграции на пустой БД, backend/frontend tests. Финансовые, авторизационные и платёжные тесты не откладываются до окончания пилота.

### 22.1. Деньги и выручка
- A1. Начальный остаток 100 000, поступление 50 000, выплата 20 000: итог 130 000 RUB.
- A2. Перевод 30 000 между своими кошельками: общий остаток неизменен, внешний денежный поток 0.
- A3. Вклад собственника 100 000: деньги и financing растут, выручка не меняется.
- A4. Аванс 60 000 без продажи: cash +60 000; выручка 0 только при полном известном покрытии источника продаж.
- A5. Продажа 120 000 с НДС 20 000, оплата 60 000: net revenue 100 000, cash 60 000.
- A6. Источник продаж отсутствует: revenue null/unavailable, не 0 и не cash-in.
- A7. Всего 300 000, ограниченный депозит 100 000, резерв 50 000: available 200 000, headroom 150 000.
- A8. Нет начального остатка: баланс unavailable.
- A9. Подтверждённый межфирменный перевод: индивидуальные отчёты отражают поток; группа исключает обе ноги только при включении обеих фирм.

### 22.2. Прогноз
- F1. Cash 100 000, завтра in 20 000/out 150 000: closing −30 000, gap 30 000.
- F2. План 100 000, оплачено 40 000: в прогнозе остаётся 60 000.
- F3. У А 200 000, у Б 0, завтра выплата Б 50 000: алерт Б сохраняется при положительном остатке группы.
- F4. Бюджет расхода 100 000 и плановый платёж 100 000: прогноз 100 000, не 200 000.
- F5. Перенос expected_date не меняет due_date и не скрывает просрочку.
- F6. Повторение на 31 число в феврале создаётся на последний день один раз.
- F7. Консервативный сценарий: expected in 100 000 → 80 000 через 7 дней; confirmed не меняется.
- F8. Уже учтённый факт на дату cutoff не попадает в прогноз повторно.

### 22.3. Бюджеты и аномалии
- B1. План к дате 100 000, расход 120 000: +20 000 и +20%; характер неблагоприятный, порог алерта проверяется отдельно.
- B2. План 0, факт 10 000: percent null, статус «вне бюджета».
- B3. Сумма дневных распределений равна месячному плану до копейки.
- B4. Бюджет net revenue сравнивается с net revenue, не со всеми поступлениями.
- N1. 10 прошлых расходов, медиана 10 000, текущий 50 000: unusual payment при выполнении порогов.
- N2. Только 3 прошлые операции: insufficient_history, не статистическая аномалия.
- N3. Повторный расчёт обновляет один алерт, а не создаёт дубль.

### 22.4. Импорт
- I1. Повтор файла: 0 новых canonical transactions.
- I2. Одинаковые дата/сумма/описание с разными external IDs: две допустимые операции.
- I3. Однозначно сопоставленный платёж из банка и 1С: одна canonical transaction, две source identities.
- I4. Изменившийся payload того же external_id: предложенная ревизия, не новый платёж.
- I5. Невалидная дата/валюта/кошелёк: явная ошибка строки, без тихого исправления.
- I6. Письмо сегодня с покрытием вчера: coverage остаётся вчера.
- I7. Перезапуск IMAP worker не повторяет импорт.
- I8. Частичный импорт имеет отчёт ошибок и соответствующие quality flags.
- I9. Ручная заблокированная классификация сохраняется.

### 22.5. Права и email
- S1. Пользователь А не читает Б через API, экспорт, callback, jobs или групповую сводку.
- S2. Известный UUID другого tenant не даёт доступ.
- S3. Контекст tenant не протекает через пул соединений и workers.
- AUTH1. Нормализованный повтор email не создаёт второго пользователя.
- AUTH2. Неподтверждённый email не получает production finance/checkout.
- AUTH3. Просроченные и использованные токены отвергаются.
- AUTH4. Reset отзывает старые сессии; новый пароль работает.
- AUTH5. Forgot-password не раскрывает наличие аккаунта.
- AUTH6. Приглашённый сотрудник использует существующую подписку.

### 22.6. Telegram
- T1. Просроченный или использованный link-token не привязывает аккаунт.
- T2. Без веб-подтверждения pending binding не получает финансовые данные.
- T3. Повтор update/confirm создаёт одну учётную операцию.
- T4. Два workers и перезапуск создают один scheduled snapshot за local_date.
- T5. Права отозваны после enqueue: сообщение отменяется перед send.
- T6. 429 соблюдает retry_after, 403 отключает binding, неоднозначный timeout даёт unknown без слепого повтора.
- T7. Части укладываются в лимит, HTML экранирован, данные из одной версии snapshot.
- T8. Устаревший источник даёт предупреждение; отсутствующая выручка не заменяется cash-in.
- T9. /stop отменяет будущую рассылку и очередь.
- T10. Без Bot Token приложение запускается, тесты работают с mock.
- T11. Ввод в кассу допускает posted; ввод в банковский кошелёк ожидает сверки, не удваивает баланс.
- T12. Групповая сводка сохраняет риски отдельных фирм.

### 22.7. Месячная подписка и платежи
- PAY1. Месячная цена 1/2/3/5 фирм: 2 500/4 000/5 500/8 500 RUB.
- PAY2. Подмена цены/валюты/tenant на клиенте не меняет серверный invoice.
- PAY3. Return URL без succeeded не даёт доступ.
- PAY4. Повтор webhook и reconciliation дают одну activation.
- PAY5. Неверные amount/currency/shop/test/metadata не активируют подписку.
- PAY6. Pending/canceled не дают доступ; verified succeeded даёт.
- PAY7. Create timeout не создаёт двойного списания.
- PAY8. Раннее продление не сокращает текущий период.
- PAY9. Вторая неоплаченная фирма заблокирована.
- PAY10. Оплаченный upgrade увеличивает лимит, не меняет period_end.
- PAY11. Downgrade применяется в следующем периоде без самовольного возврата.
- PAY12. Expiry блокирует финансовые записи/import/jobs/Telegram, но сохраняет login/billing.
- PAY13. Финансовое сообщение после paid_through не отправляется.
- PAY14. Test payment не активирует live tenant.
- PAY15. Параллельные изменения подписки не удваивают entitlements.
- PAY16. Оплата SaaS не создаёт клиентскую CashTransaction автоматически.
- PAY17. Обязательная receipt-конфигурация валидируется, произвольного VAT default нет.
- PAY18. Пропущенный webhook восстанавливается сверкой.
- PAY19. Refund меняет доступ по согласованной policy, данные сохраняются.
- PAY20. Месячные границы на 29/30/31 число и в високосном году стабильны.

### 22.8. Годовая подписка
- YEAR1. Утверждённые 15%: 1/2/3/5 фирм → 25 500/40 800/56 100/86 700 RUB за год.
- YEAR2. Новая конфигурация скидки не пересчитывает оплаченный период.
- YEAR3. Подмена скидки на frontend игнорируется сервером.
- YEAR4. Версия предложения 15% утверждена; live блокируется только при отсутствии реальных предпосылок запуска.
- YEAR5. Полный год дополнительной фирмы 15 300; ровно половина оставшегося периода 7 650 RUB.
- YEAR6. Upgrade использует скидку оплаченного периода, не новую глобальную настройку.
- YEAR7. Календарный год и leap-year anchor рассчитаны корректно.
- YEAR8. Month→year начинается после оплаченного месячного периода.
- YEAR9. Year→month не прерывает текущий год.
- YEAR10. Двойной checkout/webhook не создаёт перекрывающиеся периоды.
- YEAR11. Сумма discounted receipt lines равна payment amount до копейки.
- YEAR12. Непроверенный/canceled/test платёж не даёт live annual access.
- YEAR13. Напоминания не выполняют автоматических списаний.
- YEAR14. В 11-й месяц доступ активен, в paid_through прекращается.
- YEAR15. Уменьшение фирм действует в следующем периоде без автоматического частичного возврата.
- YEAR16. Подписка даёт оплаченный company scope, не неограниченное число фирм.
- YEAR17. Будущий оплаченный год не меняет текущие entitlements раньше своего начала.

## 23. Этапы разработки и Definition of Done

### Этап 0. Проектирование
Изучить существующий репозиторий. Подготовить architecture, ER, accounting/billing policies, decision log и план вертикальных срезов. Не писать приложение одним проходом.

### Этап 1. Основа и авторизация
Repo, Compose, CI, email register/verify/login/reset, tenant/company/RBAC, initial migrations.
DoD: AUTH и отрицательные S-тесты; запуск с чистой БД.

### Этап 2. Платная beta
Месяц/год со скидкой 15%, тестовый адаптер ЮKassa, invoices, inbox, reconciliation, entitlements, expiry, экран тарифа.
DoD: PAY/YEAR-тесты; реальные внешние действия отключены. Остальные модули сразу используют billing guard.

### Этап 3. Денежный факт
Кошельки, начальные остатки, операции, revisions, переводы.
DoD: тесты A.

### Этап 4. Импорт и классификация
CSV/XLSX/ClientBank, preview, dedup, source identities, rules.
DoD: I1–I5, I9; опубликованные fixtures и явное отклонение неизвестного формата.

### Этап 5. Выручка и отчётность
RevenueEntry, dashboard, ДДС, drill-down, quality flags.
DoD: cash/revenue разделены; приложение использует реальный API, не production mocks.

### Этап 6. Планирование
Events, recurrence, matches, obligations, forecast и групповой scope.
DoD: F-тесты и межфирменные переводы A9.

### Этап 7. Бюджет и сигналы
Бюджеты, plan-fact, anomaly engine, alert lifecycle, настройки порогов.
DoD: B/N-тесты.

### Этап 8. Telegram
Привязка, команды, ввод, snapshots/outbox, расписание.
DoD: T-тесты на mock; реальный smoke test только с разрешения владельца.

### Этап 9. Автоматический сбор
IMAP, согласованный формат 1С, coverage, retries, source health.
DoD: I6–I8 и отсутствие дублей после рестарта.

### Этап 10. Подготовка пилота
Hardening, mobile, восстановление резервной копии, нагрузка, docs, сверка реальных пилотных данных.
DoD: измеренный acceptance report и security review.

После каждого этапа предоставить: реализованные функции, изменённые файлы, миграции, команды запуска/проверки, фактические результаты тестов, ограничения и следующий шаг. Если команда не запускалась, прямо указать это. Не заменять существующий репозиторий без причины.

Критерии готовности пилота:
- email-auth и reset проверены;
- месячные/годовые платежи протестированы, доступ активируется идемпотентно;
- остатки двух фирм сверены с источниками;
- импорт не дублирует операции;
- прогноз объясняет причины риска и учитывает частичные оплаты;
- бюджет и выручка сравниваются на сопоставимой основе;
- дайджест соблюдает права, оплату и актуальность;
- окончание и продление подписки проверены;
- backup восстановлен в тесте;
- данные продавца, оферта, фискализация, инфраструктура готовы к live.

Реальные цифры проверяют заказчик/финансист. Реальные платежи и Telegram smoke test выполняются только после разрешения. Оценки сроков не выдавать за гарантию.

## 24. Опциональный AI после достоверного ядра

Финансовые расчёты и пороги алертов не делегируются LLM.
LLM может сформулировать краткое объяснение на основании валидированного metrics JSON и разрешённых source refs. Числа вставляет детерминированный renderer; неподтверждённые причины и вероятности запрещены.
Внешний провайдер выключен по умолчанию. Согласие и политика передачи данных определяются отдельно.
При ошибке AI весь дайджест работает по шаблону. Текст вложений — недоверенные данные, не инструкции системе. Логировать ссылки/версии без лишних персональных данных.
Свободный AI-чат требует отдельного ТЗ по tools, scopes и evals.

## 25. Единый стартовый промпт для Cursor

Ты — senior full-stack engineer и архитектор финансового SaaS. Реализуй «Финансовый автопилот» по этому единому ТЗ версии 2.0, последовательно по этапам.

Сначала изучи существующий репозиторий. Составь architecture, ER, финансовые инварианты, billing policy, decision log и план вертикальных срезов. Затем реализуй текущий этап и выполни доступные проверки. Не пытайся написать весь проект за один проход.

Обязательные правила:
1. Decimal/NUMERIC, суммы в API строками. Поступления не равны выручке; денежный поток не равен прибыли.
2. Tenant isolation, RBAC, company entitlements, paid_through и подтверждённый email проверяются на сервере, в jobs и перед send.
3. Beta платная: месяц 2500 RUB за первую фирму + 1500 RUB за каждую следующую; год = 12 × месячная цена × 0.85. Годовая скидка 15% утверждена. Версии цен и оплаченные snapshots неизменяемы.
4. ЮKassa hosted checkout. Return URL не активирует доступ. Обязательны проверенный через API succeeded, идемпотентная DB activation и reconciliation.
5. Email register/verify/login/reset обязательны. Telegram — дополнительный канал с веб-подтверждением привязки.
6. Нет данных — unavailable/quality flags, не фиктивный ноль. Одно финансовое ядро для web и бота.
7. План, бюджет и обязательства не дублируют поток; банковский и 1С-источники одного платежа связаны с одним canonical fact.
8. Кассовый разрыв фирмы не скрывается положительным cash группы; restricted funds не считаются available.
9. Поддерживаются опубликованные форматы 1С/adapters; неизвестный формат явно отклоняется.
10. Реальные сообщения, email, live payments и refunds выключены до разрешения. Не регистрируй webhook и не меняй production без approval. Автотесты используют provider/bot/email mocks.
11. Не отключай тесты/авторизацию ради зелёного CI и не подменяй реальные функции production mocks.
12. После этапа сообщи изменения, миграции, команды, фактические тесты и ограничения. Незапущенные команды обозначь прямо.

Начни с этапов 0–1, затем этапа 2 с month/year и утверждёнными 15%. Вынеси данные продавца и пилотные файлы 1С в readiness list, но не останавливай test/mock-разработку из-за отсутствия production secrets. Используй безопасные defaults ТЗ; существенные спорные решения фиксируй в decision log.
