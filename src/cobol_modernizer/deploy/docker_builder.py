"""Deterministic container build from a generated Spring Boot project.
In production the project body is pulled from MinIO (artifact.object_uri) and
extracted; here `context_dir` is the build context. Returns a DeploySpec whose
image_digest is the reproducibility anchor recorded on the `deployment` row."""
from __future__ import annotations

import json
import subprocess
from cobol_modernizer.deploy.models import DeploySpec


def build_command(*, context_dir: str, image_ref: str) -> list[str]:
    return [
        "docker", "build",
        "--progress", "plain",
        "--tag", image_ref,
        context_dir,
    ]


def _image_digest(image_ref: str) -> str:
    out = subprocess.run(
        ["docker", "inspect", "--format", "{{json .Id}}", image_ref],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return json.loads(out)  # "sha256:..."


def build_image(*, workspace_id: str, artifact_id: str, slice_name: str,
                context_dir: str, image_ref: str) -> DeploySpec:
    subprocess.run(build_command(context_dir=context_dir, image_ref=image_ref),
                   check=True)
    return DeploySpec(
        workspace_id=workspace_id, artifact_id=artifact_id, slice_name=slice_name,
        image_ref=image_ref, image_digest=_image_digest(image_ref),
    )
