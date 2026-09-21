"""The envelope the engine hands over: a typed request plus the paths it may touch.

Validated with the standard library alone, because the runtime has no pydantic. The rule that
matters is at the bottom of this file: the runtime opens nothing whose path is not in here.
"""

import json
import os

REQUIRED_TOP = ("schema_version", "task_id", "runtime_version", "request", "context")
REQUIRED_REQUEST = ("operation", "operation_id", "project_id", "target", "parameters")
REQUIRED_CONTEXT = ("project_root", "task_dir", "out_dir", "engine_series")


def load_envelope(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    missing = [key for key in REQUIRED_TOP if key not in data]
    if missing:
        raise ValueError("incomplete envelope: %s" % missing)
    if data["schema_version"] != "1.0":
        raise ValueError("unsupported envelope schema_version: %s" % data["schema_version"])
    request_missing = [key for key in REQUIRED_REQUEST if key not in data["request"]]
    if request_missing:
        raise ValueError("incomplete request: %s" % request_missing)
    context_missing = [key for key in REQUIRED_CONTEXT if key not in data["context"]]
    if context_missing:
        raise ValueError("incomplete context: %s" % context_missing)
    return data


class Context:
    """Every path the runtime is allowed to touch, and nothing else."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def from_envelope(cls, envelope):
        context = envelope["context"]
        os.makedirs(context["out_dir"], exist_ok=True)
        return cls(
            task_id=envelope["task_id"],
            runtime_expected_version=envelope["runtime_version"],
            runtime_hash=envelope.get("runtime_hash"),
            project_id=envelope["request"]["project_id"],
            project_root=context["project_root"],
            task_dir=context["task_dir"],
            out_dir=context["out_dir"],
            engine_series=context["engine_series"],
            bundle_dir=context.get("bundle_dir"),
            bundle=context.get("bundle") or {},
            destination_root=context.get("destination_root", "/Game/Fluid"),
            content_root=context.get("content_root"),
            next_version=int(context.get("next_version", 1)),
            budgets=context.get("budgets") or {},
            test_hooks=context.get("test_hooks") or {},
        )

    def out(self, name):
        return os.path.join(self.out_dir, name)

    def bundle_file(self, role):
        """A file of the bundle, by the role its manifest gave it. Never an arbitrary path."""
        for entry in self.bundle.get("files") or []:
            if entry.get("role") == role:
                if not self.bundle_dir:
                    raise ValueError("the envelope names no bundle folder")
                return os.path.join(self.bundle_dir, entry["path"].replace("/", os.sep))
        raise ValueError("the bundle carries no file with role %r" % role)

    def instance(self, asset_id=None):
        """The bundle instance this run is about."""
        instances = self.bundle.get("instances") or []
        if asset_id:
            for entry in instances:
                if entry.get("asset_id") == asset_id:
                    return entry
            raise ValueError("the bundle describes no instance for asset %r" % asset_id)
        if not instances:
            raise ValueError("the bundle describes no instance")
        return instances[0]

    def clips_for(self, instance_id):
        return [c for c in (self.bundle.get("clips") or []) if c.get("instance_id") == instance_id]
