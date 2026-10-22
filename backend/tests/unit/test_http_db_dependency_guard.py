"""Guard: все production HTTP DB dependencies идут через DbSession (scope=function)."""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
API_V1 = BACKEND / "app" / "api" / "v1"
DEPS = BACKEND / "app" / "api" / "deps.py"


def _v1_sources() -> list[Path]:
    return sorted(API_V1.glob("*.py"))


def test_db_session_alias_uses_function_scope() -> None:
    text = DEPS.read_text(encoding="utf-8")
    assert 'Depends(get_db, scope="function")' in text
    assert "DbSession = Annotated" in text


def test_v1_modules_do_not_depend_on_get_db_directly() -> None:
    offenders: list[str] = []
    for path in _v1_sources():
        source = path.read_text(encoding="utf-8")
        if re.search(r"Depends\s*\(\s*get_db\s*\)", source):
            offenders.append(f"{path.name}: bare Depends(get_db)")
        if "import get_db" in source or ", get_db," in source:
            offenders.append(f"{path.name}: imports get_db")
        if re.search(r"Depends\s*\(\s*get_db\s*,", source) and 'scope="function"' not in source:
            offenders.append(f"{path.name}: Depends(get_db) without scope=function")
    assert not offenders, "\n".join(offenders)


def test_v1_route_handlers_use_db_session_annotation() -> None:
    missing: list[str] = []
    for path in _v1_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(
                isinstance(d, ast.Attribute)
                and isinstance(d.value, ast.Name)
                and d.value.id == "router"
                and d.attr in {"get", "post", "put", "patch", "delete"}
                for d in node.decorator_list
            ):
                continue
            has_db = any(
                isinstance(arg, ast.arg)
                and arg.annotation
                and (
                    (isinstance(arg.annotation, ast.Name) and arg.annotation.id == "DbSession")
                    or (
                        isinstance(arg.annotation, ast.Subscript)
                        and isinstance(arg.annotation.value, ast.Name)
                        and arg.annotation.value.id == "DbSession"
                    )
                )
                for arg in node.args.args
            )
            if not has_db:
                missing.append(f"{path.name}:{node.name}")
    assert not missing, "handlers without DbSession:\n" + "\n".join(missing)


def test_openapi_operation_count_unchanged() -> None:
    from app.main import create_app

    app = create_app()
    ops = 0
    for methods in app.openapi()["paths"].values():
        ops += sum(1 for m in methods if m in {"get", "post", "put", "patch", "delete"})
    assert ops == 109
