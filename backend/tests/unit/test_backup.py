import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backup = _load("backup")
restore = _load("restore")


def test_backup_without_passphrase_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "copy.enc"
    monkeypatch.delenv("BACKUP_PASSPHRASE", raising=False)
    try:
        backup.require_passphrase()
        raised = False
    except SystemExit:
        raised = True
    assert raised is True
    try:
        backup.create_backup(
            host="127.0.0.1",
            port=5433,
            database="finpilot_test",
            storage_dir=tmp_path,
            output=target,
            passphrase="",
        )
        refused = False
    except SystemExit:
        refused = True
    assert refused is True
    assert target.exists() is False


def test_restore_refuses_the_test_database_and_port_5432() -> None:
    try:
        backup.assert_restore_target("finpilot_test")
        allowed = True
    except SystemExit:
        allowed = False
    assert allowed is False
    try:
        backup.assert_port(5432)
        port_ok = True
    except SystemExit:
        port_ok = False
    assert port_ok is False
    backup.assert_restore_target(restore.RESTORE_DATABASE)
