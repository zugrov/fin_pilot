#!/usr/bin/env python3
"""Проверка контрактов FA-R00.4: полный режим (jsonschema + OpenAPI) или structural-only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "ingestion-delivery.schema.json"
OPENAPI_PATH = ROOT / "ingestion-proposed.openapi.yaml"
POSITIVE_DIR = ROOT / "examples"
NEGATIVE_DIR = POSITIVE_DIR / "negative"
BROKEN_SCHEMA_PATH = ROOT / "fixtures" / "schema-unresolvable-ref.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def error_path(error) -> str:
    parts = [str(p) for p in error.path]
    if error.schema_path:
        schema_tail = ".".join(str(p) for p in error.schema_path if p != "$")
        return f"instance={'.'.join(parts) or '$'} schema={schema_tail} message={error.message}"
    return f"instance={'.'.join(parts) or '$'} message={error.message}"


def resolve_ref(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"only local refs allowed, got {ref}")
    node: object = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"unresolvable ref {ref} at {part!r}")
        node = node[part]
    if not isinstance(node, dict):
        raise ValueError(f"ref {ref} did not resolve to object")
    return node


def collect_refs(schema: dict, root: dict, seen: set[str]) -> list[str]:
    failures: list[str] = []
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            if ref in seen:
                return failures
            seen.add(ref)
            try:
                target = resolve_ref(root, ref)
            except ValueError as exc:
                failures.append(str(exc))
            else:
                failures.extend(collect_refs(target, root, seen))
        for value in schema.values():
            failures.extend(collect_refs(value, root, seen))
    elif isinstance(schema, list):
        for item in schema:
            failures.extend(collect_refs(item, root, seen))
    return failures


def structural_check(instance: object, schema: dict, root: dict, path: str) -> list[str]:
    """Урезанная проверка без jsonschema (режим structural-only)."""
    errors: list[str] = []
    if schema.get("type") == "object":
        if not isinstance(instance, dict):
            return [f"{path}: expected object"]
        if schema.get("additionalProperties") is False:
            allowed = set(schema.get("properties", {}))
            for key in instance:
                if key not in allowed:
                    errors.append(f"{path}.{key}: extra property")
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required {key}")
        for key, subschema in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(structural_check(instance[key], subschema, root, f"{path}.{key}"))
        for rule in schema.get("allOf", []):
            if "if" in rule and "then" in rule:
                cond = rule["if"].get("properties", {})
                if all(instance.get(k) == v.get("const") for k, v in cond.items() if "const" in v):
                    errors.extend(structural_check(instance, rule["then"], root, path))
    elif "$ref" in schema:
        return structural_check(instance, resolve_ref(root, schema["$ref"]), root, path)
    elif schema.get("type") == "string" and isinstance(instance, str):
        if schema.get("format") == "uuid" and len(instance) != 36:
            errors.append(f"{path}: uuid length (structural; format not fully checked)")
    return errors


def run_structural(schema: dict, positive: list[Path], negative: list[Path]) -> int:
    print("MODE structural-only (jsonschema/OpenAPI not required)")
    failures = 0
    ref_errors = collect_refs(schema, schema, set())
    if ref_errors:
        failures += 1
        print("FAIL schema $ref resolution")
        for err in ref_errors:
            print(f"  {err}")
    else:
        print("OK   schema local $ref resolution (manual walk)")
    for path in positive:
        errors = structural_check(load_json(path), schema, schema, path.name)
        if errors:
            failures += 1
            print(f"FAIL {path.name}")
            for err in errors[:5]:
                print(f"  {err}")
        else:
            print(f"OK   {path.name} (structural)")
    for path in negative:
        errors = structural_check(load_json(path), schema, schema, path.name)
        if not errors:
            failures += 1
            print(f"FAIL {path.name} expected invalid (structural)")
        else:
            print(f"OK   {path.name} rejected (structural)")
    print(f"RESULT structural-only failures={failures}")
    return failures


def run_full() -> int:
    try:
        import yaml
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError, ValidationError
        from openapi_spec_validator import validate as validate_openapi
    except ImportError as exc:
        print(f"INCOMPLETE full validation: missing dependency ({exc})")
        print("Install tools from validation-tools.lock.txt into external venv.")
        return 2

    schema = load_json(SCHEMA_PATH)
    format_checker = FormatChecker()
    failures = 0

    print("MODE full (jsonschema Draft 2020-12 + FormatChecker + openapi-spec-validator)")

    try:
        Draft202012Validator.check_schema(schema)
        print("OK   ingestion-delivery.schema.json check_schema")
    except SchemaError as exc:
        failures += 1
        print(f"FAIL check_schema: {exc.message}")

    ref_errors = collect_refs(schema, schema, set())
    if ref_errors:
        failures += 1
        print("FAIL schema local $ref resolution")
        for err in ref_errors:
            print(f"  {err}")
    else:
        print("OK   schema local $ref resolution")

    if BROKEN_SCHEMA_PATH.is_file():
        broken = load_json(BROKEN_SCHEMA_PATH)
        try:
            resolve_ref(broken, broken["properties"]["x"]["$ref"])
            failures += 1
            print("FAIL fixtures/schema-unresolvable-ref.json $ref unexpectedly resolved")
        except ValueError as exc:
            print(f"OK   broken schema $ref rejected: {exc}")

    validator = Draft202012Validator(schema, format_checker=format_checker)
    print(
        "INFO format checking enabled for: "
        + ", ".join(sorted(format_checker.checkers.keys()))
    )

    positive = sorted(POSITIVE_DIR.glob("*.json"))
    for path in positive:
        instance = load_json(path)
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        if errors:
            failures += 1
            print(f"FAIL positive {path.name}")
            print(f"  {error_path(errors[0])}")
        else:
            print(f"OK   positive {path.name}")

    negative = sorted(NEGATIVE_DIR.glob("*.json"))
    for path in negative:
        instance = load_json(path)
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        if not errors:
            failures += 1
            print(f"FAIL negative {path.name} (expected rejection, got valid)")
        else:
            print(f"OK   negative {path.name}")
            print(f"  {error_path(errors[0])}")

    if OPENAPI_PATH.is_file():
        spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        try:
            validate_openapi(spec)
            print("OK   ingestion-proposed.openapi.yaml (OpenAPI 3.0.3)")
        except Exception as exc:
            failures += 1
            print(f"FAIL OpenAPI validation: {exc}")
    else:
        failures += 1
        print("FAIL missing ingestion-proposed.openapi.yaml")

    print(f"RESULT full failures={failures}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FA-R00.4 contract artifacts")
    parser.add_argument(
        "--mode",
        choices=("full", "structural-only"),
        default="full",
        help="full requires jsonschema and openapi-spec-validator in current interpreter",
    )
    args = parser.parse_args()
    schema = load_json(SCHEMA_PATH)
    positive = sorted(POSITIVE_DIR.glob("*.json"))
    negative = sorted(NEGATIVE_DIR.glob("*.json"))
    if args.mode == "structural-only":
        code = run_structural(schema, positive, negative)
        return 1 if code else 0
    return run_full()


if __name__ == "__main__":
    sys.exit(main())
