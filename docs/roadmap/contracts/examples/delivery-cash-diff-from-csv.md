# Отличия JSON records от cash_transactions.csv

CSV: фиксированный порядок колонок, одна строка = одна запись, файл целиком.

Envelope `json_records`:

- те же имена полей, что в `docs/import-formats.md`;
- суммы и даты — строки в JSON (schema pattern / format date);
- `currency` только `RUB`;
- порядок полей в объекте не значим;
- лишние свойства запрещены (`additionalProperties: false`);
- один part может содержать несколько records без повторной шапки CSV.

ClientBank и XLSX в envelope передаются как `format: clientbank|xlsx` с
`content_sha256` байтов, без inline records.
