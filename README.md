# FinPilot

## Деплой (HTTP по IP, без TLS)

**Плейсхолдеры:** `DEPLOY_SSH_ALIAS` — имя `Host` в `~/.ssh/config`; `APP_ROOT` — каталог на сервере (по умолчанию `/opt/finpilot`); `IMAGE_TAG` — тег образов (см. `infra/docker-compose.prod.yml`).

Секреты только в `{APP_ROOT}/.env` на сервере (файл в git не коммитится).

**Деплой** (обновить `main` и пересоздать контейнеры):

```bash
ssh "${DEPLOY_SSH_ALIAS}" 'set -euo pipefail; cd "${APP_ROOT}"; git fetch origin main; git checkout -B main origin/main; docker compose --env-file .env -f infra/docker-compose.prod.yml -f infra/docker-compose.prod.ip.override.yml up -d'
```

**Логи** (последние 200 строк, follow):

```bash
ssh "${DEPLOY_SSH_ALIAS}" 'cd "${APP_ROOT}" && docker compose --env-file .env -f infra/docker-compose.prod.yml -f infra/docker-compose.prod.ip.override.yml logs -f --tail=200'
```

**Откат образа** (подставьте сохранённый предыдущий тег `PREV_TAG`):

```bash
ssh "${DEPLOY_SSH_ALIAS}" 'cd "${APP_ROOT}"; docker tag finpilot-api:"${IMAGE_TAG}" finpilot-api:"${IMAGE_TAG}"-retired; docker tag finpilot-api:"${PREV_TAG}" finpilot-api:"${IMAGE_TAG}"; docker tag finpilot-frontend:"${PREV_TAG}" finpilot-frontend:"${IMAGE_TAG}"; docker compose --env-file .env -f infra/docker-compose.prod.yml -f infra/docker-compose.prod.ip.override.yml up -d'
```

Доставка образов без registry: локально `docker build -t finpilot-api:"${IMAGE_TAG}" backend` и `finpilot-frontend:"${IMAGE_TAG}"`, затем `docker save finpilot-api:"${IMAGE_TAG}" finpilot-frontend:"${IMAGE_TAG}" | ssh "${DEPLOY_SSH_ALIAS}" docker load`. Если локального Docker нет — сборка на сервере из checkout: `docker build --network=host -t finpilot-api:"${IMAGE_TAG}" backend` (и аналогично frontend).

Первый запуск без домена: `infra/docker-compose.prod.ip.override.yml` подключает `infra/Caddyfile.ip` (только HTTP, порт 80).
