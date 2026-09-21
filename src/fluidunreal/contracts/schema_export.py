"""Export of the JSON Schemas (Draft 2020-12) from the pydantic source of truth.

The hand-off bundle's schema is not generated here: it belongs to fluidblend. A copy is vendored
under `schemas/` and a test fails if it drifts from the installed dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

from fluidblend.contracts.capabilities import CapabilitiesReport
from fluidblend.contracts.common import OperationResult
from fluidblend.contracts.handoff import HandoffBundle
from fluidblend.contracts.project import DependencyLock, RevisionsFile
from fluidblend.contracts.tasks import TaskRecord

from fluidunreal.contracts.operations import OPERATIONS, OperationRequest
from fluidunreal.contracts.plans import Plan as UnrealPlan
from fluidunreal.contracts.project import LocalConfig, ProjectManifest
from fluidunreal.contracts.reports import AcceptedBundle, AuditReport, ImportedAsset, Measurement

ROOT_SCHEMAS = {
    "project": ProjectManifest,
    "local-config": LocalConfig,
    "operation-request": OperationRequest,
    "operation-result": OperationResult,
    "task": TaskRecord,
    "plan": UnrealPlan,
    "capabilities": CapabilitiesReport,
    "revisions": RevisionsFile,
    "dependencies-lock": DependencyLock,
    "accepted-bundle": AcceptedBundle,
    "imported-asset": ImportedAsset,
    "audit-report": AuditReport,
    "measurement": Measurement,
}

# Owned by fluidblend: vendored with its version, compared to the dependency by a test.
VENDORED = {"handoff-bundle": HandoffBundle}


def dumps_canonical(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for name, model in {**ROOT_SCHEMAS, **VENDORED}.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://fluidunreal.local/schemas/{name}.json"
        schemas[name] = schema
    for op_name, spec in OPERATIONS.items():
        schema = spec.params_model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://fluidunreal.local/schemas/operations/{op_name}.json"
        schema["description"] = spec.description
        schema["x-fluidunreal"] = {
            "backend": spec.backend,
            "op_class": spec.op_class,
            "lot": spec.lot,
            "available": spec.available,
            **spec.execution_contract(),
        }
        schemas[f"operations/{op_name}"] = schema
    return schemas


def export_all(out_dir: Path) -> int:
    schemas = build_schemas()
    (out_dir / "operations").mkdir(parents=True, exist_ok=True)
    for name, schema in schemas.items():
        path = out_dir / f"{name}.json"
        path.write_text(dumps_canonical(schema), encoding="utf-8")
    index = {
        "schemas": sorted(schemas),
        "operations": {name: spec.execution_contract() for name, spec in OPERATIONS.items()},
    }
    (out_dir / "index.json").write_text(dumps_canonical(index), encoding="utf-8")
    return len(schemas)


def check_up_to_date(out_dir: Path) -> list[str]:
    """Paths whose file on disk differs from what the contracts produce now."""
    stale: list[str] = []
    for name, schema in build_schemas().items():
        path = out_dir / f"{name}.json"
        if not path.exists() or path.read_text(encoding="utf-8") != dumps_canonical(schema):
            stale.append(f"{name}.json")
    return stale
