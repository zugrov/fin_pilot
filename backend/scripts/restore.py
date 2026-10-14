"""Восстановление только в базу finpilot_restore на порту, отличном от 5432."""

import os
import subprocess
import tempfile
from pathlib import Path

import psycopg
from backup import RESTORE_DATABASE, assert_port, assert_restore_target, require_passphrase, tool
from psycopg import sql


def restore_backup(
    *,
    host: str,
    port: int,
    storage_dir: Path,
    source: Path,
    passphrase: str,
) -> None:
    if not passphrase or not source.is_file():
        raise SystemExit("Нужны пароль и файл копии")
    assert_port(port)
    assert_restore_target(RESTORE_DATABASE)
    storage_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        bundle = folder / "bundle.tar"
        env = os.environ.copy()
        env["BACKUP_PASSPHRASE"] = passphrase
        subprocess.run(
            [
                "openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-pbkdf2",
                "-salt",
                "-pass",
                "env:BACKUP_PASSPHRASE",
                "-in",
                str(source),
                "-out",
                str(bundle),
            ],
            check=True,
            env=env,
        )
        subprocess.run(["tar", "-xf", str(bundle), "-C", str(folder)], check=True)
        _recreate(host, port)
        subprocess.run(
            [
                tool("pg_restore"),
                "-h",
                host,
                "-p",
                str(port),
                "-d",
                RESTORE_DATABASE,
                "--no-owner",
                "--exit-on-error",
                str(folder / "db.dump"),
            ],
            check=True,
        )
        subprocess.run(
            ["tar", "-xf", str(folder / "files.tar"), "-C", str(storage_dir)],
            check=True,
        )


def _recreate(host: str, port: int) -> None:
    name = sql.Identifier(RESTORE_DATABASE)
    with psycopg.connect(f"postgresql://{host}:{port}/postgres", autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (RESTORE_DATABASE,),
        )
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(name))
        connection.execute(sql.SQL("CREATE DATABASE {}").format(name))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Восстановление в finpilot_restore")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TEST_PG_PORT", "5433")))
    parser.add_argument("--storage", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    restore_backup(
        host=args.host,
        port=args.port,
        storage_dir=args.storage,
        source=args.input,
        passphrase=require_passphrase(),
    )


if __name__ == "__main__":
    main()
