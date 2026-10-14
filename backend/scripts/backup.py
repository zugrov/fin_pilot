"""Шифрованная копия базы и каталога вложений. Без пароля файл не пишется."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

RESTORE_DATABASE = "finpilot_restore"
FORBIDDEN_DATABASES = {"finpilot", "finpilot_test", "postgres"}


def require_passphrase() -> str:
    value = os.environ.get("BACKUP_PASSPHRASE", "")
    if not value or "\n" in value:
        raise SystemExit("Нужен BACKUP_PASSPHRASE")
    return value


def assert_port(port: int) -> None:
    if port == 5432:
        raise SystemExit("Порт 5432 не используется")


def assert_backup_source(database: str) -> None:
    if database == "finpilot" or database == RESTORE_DATABASE:
        raise SystemExit("Эта база не копируется этим скриптом")


def assert_restore_target(database: str) -> None:
    if database != RESTORE_DATABASE or database in FORBIDDEN_DATABASES:
        raise SystemExit("Восстановление только в finpilot_restore")


def tool(name: str) -> str:
    override = os.environ.get("PG_DUMP" if name == "pg_dump" else "PG_RESTORE", "")
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    home = Path.home() / ".local" / "pg16" / "bin" / name
    if home.is_file():
        return str(home)
    raise SystemExit(f"Не найден {name}")


def create_backup(
    *,
    host: str,
    port: int,
    database: str,
    storage_dir: Path,
    output: Path,
    passphrase: str,
) -> None:
    if not passphrase:
        raise SystemExit("Нужен BACKUP_PASSPHRASE")
    assert_port(port)
    assert_backup_source(database)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        dump_path = folder / "db.dump"
        files_path = folder / "files.tar"
        bundle_path = folder / "bundle.tar"
        subprocess.run(
            [
                tool("pg_dump"),
                "-h",
                host,
                "-p",
                str(port),
                "-Fc",
                "-d",
                database,
                "-f",
                str(dump_path),
            ],
            check=True,
        )
        if storage_dir.is_dir():
            subprocess.run(
                ["tar", "-cf", str(files_path), "-C", str(storage_dir), "."],
                check=True,
            )
        else:
            marker = folder / ".keep"
            marker.write_text("", encoding="utf-8")
            subprocess.run(
                ["tar", "-cf", str(files_path), "-C", str(folder), ".keep"],
                check=True,
            )
        subprocess.run(
            ["tar", "-cf", str(bundle_path), "-C", str(folder), "db.dump", "files.tar"],
            check=True,
        )
        temporary = output.with_suffix(output.suffix + ".partial")
        env = os.environ.copy()
        env["BACKUP_PASSPHRASE"] = passphrase
        subprocess.run(
            [
                "openssl",
                "enc",
                "-aes-256-cbc",
                "-pbkdf2",
                "-salt",
                "-pass",
                "env:BACKUP_PASSPHRASE",
                "-in",
                str(bundle_path),
                "-out",
                str(temporary),
            ],
            check=True,
            env=env,
        )
        temporary.replace(output)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Шифрованная копия finpilot_test")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TEST_PG_PORT", "5433")))
    parser.add_argument("--database", default="finpilot_test")
    parser.add_argument("--storage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    create_backup(
        host=args.host,
        port=args.port,
        database=args.database,
        storage_dir=args.storage,
        output=args.output,
        passphrase=require_passphrase(),
    )


if __name__ == "__main__":
    main()
