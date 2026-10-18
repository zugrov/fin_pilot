"""Подготовка БД перед Playwright (migrate + truncate + seed)."""

from tests.e2e.seed import run_seed

if __name__ == "__main__":
    run_seed()
