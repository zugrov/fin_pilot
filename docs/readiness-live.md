# Готовность к live-запуску

Проверка 2026-10-14, тогда `main` `c8ee41d`. Публичный репозиторий: `https://github.com/zugrov/fin_pilot`. Первый push — этот коммит, без локальных черновиков. `SEND_REAL_EMAIL`, `SEND_EXTERNAL_MESSAGES`, `SEND_LIVE_PAYMENTS` и `POLL_IMAP` не включались. Боевые платежи, письма, Telegram, IMAP и webhook не вызывались. Каталог на VPS, DNS, nginx и контейнеры не создавались.

Пока пункт не закрыт, соответствующее боевое действие выключено флагом. Успех mock-теста этот пункт не закрывает. Закрытие отмечается датой и ссылкой на решение.

План выкладки закрытого staging: `docs/runbook-staging.md`.

## Что запущено

Выполнено и прошло:

- `uv run ruff check app tests schema_sql.py alembic`
- `uv run mypy app` — 93 файла
- `TEST_PG_PORT=5433 uv run pytest` — 166 passed. Сессионная фикстура на `finpilot_test` делает upgrade, downgrade до base и снова upgrade
- отдельная пустая база `finpilot_migrate_check` на порту 5433: upgrade до `20261014_0009`, downgrade до base, база удалена. База `finpilot` на порту 5432 не создавалась
- `npm test` — 15 passed; `npm run build` (`tsc --noEmit` и production bundle)

Выполнено и не прошло: ничего из запущенного.

Не выполнено: Playwright и другой E2E, прогон `.github/workflows/ci.yml`, Docker и Compose, боевые ЮKassa, SMTP, Telegram, IMAP, webhook.

Проверено только с mock: оплата через `FakeYooKassa`, почта через mock/outbox, Telegram через `MockTelegram`, IMAP через `FakeMailbox`.

Требует Linux/VPS или внешнего сервиса: Compose, Celery prefork, TLS, внешние копии, живые интеграции и сверка файлов заказчика.

## Таблица

| Пункт | Статус | Доказательство | Ответственный | Необходимое действие | Блокирует закрытый пилот | Блокирует коммерческий запуск |
|---|---|---|---|---|---|---|
| Регистрация, подтверждение почты, сброс пароля | проверено только с mock | `backend/tests/integration/test_auth.py` | разработка | Боевой SMTP только после разрешения | нет | да |
| Месяц, год и скидка 15% | проверено только с mock | `test_year1_annual_payable`: 1 фирма `25500.00` при списке `30000.00` | разработка | Боевой магазин ЮKassa | нет | да |
| Активация идемпотентна, return URL доступ не открывает | проверено только с mock | `test_pay2_pay3_pay6_server_price_and_return_do_not_grant` | разработка | Нет | нет | нет |
| Повтор webhook не даёт вторую activation | проверено только с mock | тот же тест: два `payment.succeeded`, одна строка `billing_activations` | разработка | Боевой webhook регистрируется отдельно | нет | да |
| `paid_through` и права в API, jobs и send | проверено только с mock | `test_write_after_paid_through_is_402`, `test_t5_revoked_access_cancels_before_send`, `assert_financial_job(..., mode="send")` | разработка | Нет | нет | нет |
| Поступления не подменяют выручку | выполнено и прошло | `test_two_companies_match_published_fixtures`, `test_b4_revenue_budget_uses_net_not_receipts` | разработка | Сверка с файлами заказчика отдельно | нет | нет |
| План и факт не дублируются | выполнено и прошло | `test_f2_residual_after_match_and_void`: после сопоставления `40000.00` в прогнозе остаётся `60000.00` | разработка | Нет | нет | нет |
| Повтор импорта не создаёт операции | выполнено и прошло | `test_i1_repeat_file_creates_nothing_new`, `test_i7_restart_does_not_repeat_import` | разработка | Нет | нет | нет |
| Разрыв фирмы не скрывается группой | выполнено и прошло | `test_f3_company_gap_stays_when_group_is_positive`: разрыв `50000.00` при групповом остатке `200000.00` | разработка | Нет | нет | нет |
| Остатки двух фирм и реальные источники | не выполнено | Сверены только `cash_ok.csv`, `revenue_ok.csv`, `clientbank_ok.txt` | заказчик | Передать файлы вне репозитория | да | да |
| Шаблон выгрузки 1С и список конфигураций | не выполнено | В коде только `ClientBankExchange` 1.03 | заказчик | Согласовать шаблон с разработчиком 1С | да | да |
| Почтовый ящик и IMAP | не выполнено | `POLL_IMAP` выключен, тесты на `FakeMailbox` | заказчик | Ящик, фильтры и ключ шифрования. Флаг не включать до разрешения | нет | да |
| Продавец, НДС, чек, оферта, `RECEIPT_MODE` | не выполнено | Live checkout закрыт, пока поля пустые | заказчик | Документы продавца и режим чека | нет | да |
| Учётные данные ЮKassa, allowlist и webhook | требует внешнего сервиса | В тестах `FakeYooKassa`, webhook только пишет inbox | заказчик | Кабинет ЮKassa. `SEND_LIVE_PAYMENTS` остаётся `false` | нет | да |
| Возвраты | не выполнено | `REFUNDS_ENABLED` выключен | заказчик | Кто подтверждает возврат и на каком основании | нет | да |
| Боевая почта | требует внешнего сервиса | `SEND_REAL_EMAIL` выключен. Пустой `OUTBOUND_EMAIL_ALLOWLIST` отменяет боевую отправку до SMTP | заказчик | Домен, SPF/DKIM, адреса в списке и разрешение на отправку | нет | да |
| Боевой Telegram | требует внешнего сервиса | `SEND_EXTERNAL_MESSAGES` выключен. Пустой `TELEGRAM_CHAT_ALLOWLIST` не вызывает Bot API | заказчик | Токен, chat id в списке и решение о webhook. Репозиторий webhook не регистрирует | нет | да |
| Контур данных и передача в Telegram | не выполнено | Пункт ТЗ до пилота, решения нет | заказчик | Письменное решение до загрузки данных заказчика | да | да |
| VPS, домен, TLS, секреты вне git | требует Linux/VPS | Каталог `/fin_pilot` на VPS отсутствует. `staging.maxima-consulting.ru` в nginx нет | заказчик и разработка | Отдельное подтверждение: каталог, A-запись, новый сайт nginx. Секреты вне репозитория | да | да |
| Docker, Compose, Celery prefork | требует Linux/VPS | `infra/docker-compose.staging.yml` слушает только `127.0.0.1:8090`. На VPS не запускался | разработка | Прогон на Linux. На macOS prefork не доказан. Prod-compose на этот хост не запускать | да | да |
| Роли БД на целевом сервере | не выполнено | Роли создаёт миграция `0001`, на VPS не применялись | разработка | Миграции отдельной rolью, приложение без неё | да | да |
| Копия вне сервера, RPO 24ч и RTO 4ч | проверено локально, live не закрыт | `test_restore_keeps_amount_and_attachment` на `finpilot_restore:5433`. `scripts/backup.py` отвергает базу `finpilot` и порт 5432 | разработка | Отдельная процедура копии staging и восстановление вне VPS | да | да |
| Профиль 4 vCPU, 100 000 операций, p95 3 с | не выполнено | Один локальный прогон 10 000 операций в `docs/acceptance-stage-10.md` | разработка | Отдельный прогон на целевом железе, если цифра объявляется | нет | нет |
| E2E ключевых сценариев | не выполнено | Playwright в репозитории нет. CI его не запускает | разработка | Прогон сценариев в браузере. Ручная вёрстка этапа 10 E2E не заменяет | нет | да |
| GitHub CI | не выполнено | Workflow есть, remote `https://github.com/zugrov/fin_pilot`, этот прогон локальный | разработка | Дождаться зелёного CI | нет | да |
