"""Building the result the engine reads back. Written atomically, always before quitting."""

import hashlib
import json
import os
import tempfile
import time


def write_json_atomic(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResultBuilder:
    """What the operation produced, in the shape the engine's OperationResult expects."""

    def __init__(self, request, ctx):
        self.request = request
        self.ctx = ctx
        self.started = time.time()
        self.artifacts = []
        self.changed = []
        self.warnings = []
        self.limits = []
        self.metrics = {}
        self.next_safe_actions = []

    def add_file(self, kind, path, **metrics):
        artifact = {
            "kind": kind,
            "path": os.path.relpath(path, self.ctx.out_dir).replace(os.sep, "/"),
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
            "metrics": metrics,
        }
        self.artifacts.append(artifact)
        return artifact

    def write_report(self, name, data, kind="report"):
        path = self.ctx.out(name)
        write_json_atomic(path, data)
        return self.add_file(kind, path)

    def warn(self, text):
        if text not in self.warnings:
            self.warnings.append(text)

    def limit(self, text):
        """Something this run does not prove. Stated, never left to be assumed."""
        if text not in self.limits:
            self.limits.append(text)

    def changed_entity(self, kind, identifier, change):
        self.changed.append({"kind": kind, "id": identifier, "change": change})

    def result(self, status="succeeded", errors=None):
        metrics = dict(self.metrics)
        if self.limits:
            metrics["limits"] = self.limits
        metrics.setdefault("wall_time_ms", int((time.time() - self.started) * 1000))
        return {
            "schema_version": "1.0",
            "operation_id": self.request["operation_id"],
            "operation": self.request["operation"],
            "task_id": self.ctx.task_id,
            "status": status,
            "changed_entities": self.changed,
            "artifacts": self.artifacts,
            "warnings": self.warnings,
            "errors": errors or [],
            "metrics": metrics,
            "next_safe_actions": self.next_safe_actions,
        }
