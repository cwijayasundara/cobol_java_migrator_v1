import shutil
import pytest
from pathlib import Path
from cobol_modernizer.deploy.docker_builder import build_command, build_image

FIX = Path(__file__).parents[1] / "fixtures" / "spring_boot_project_sample"


def test_build_command_is_deterministic():
    cmd = build_command(context_dir=str(FIX), image_ref="account-view-service:test")
    # pinned, reproducible: no --pull random, fixed tag, --progress plain
    assert cmd[:2] == ["docker", "build"]
    assert "--tag" in cmd and "account-view-service:test" in cmd
    assert str(FIX) in cmd


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_build_produces_digest():
    spec = build_image(
        workspace_id="w1", artifact_id="a1",
        slice_name="account-view-service",
        context_dir=str(FIX), image_ref="account-view-service:test",
    )
    assert spec.image_digest.startswith("sha256:")
    assert spec.slice_name == "account-view-service"
