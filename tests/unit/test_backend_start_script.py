from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_start_backend_refuses_shadowed_api_port_before_uvicorn():
    script = (ROOT / "scripts/start-backend.sh").read_text()
    check = 'if _busy "$BACKEND_PORT"; then'
    uvicorn = "uv run uvicorn cobol_modernizer.api:app"
    assert check in script
    assert script.index(check) < script.index("docker compose port")
    assert script.index(check) < script.index("docker compose up")
    assert script.index(check) < script.index(uvicorn)
    assert "another process is already listening on localhost:${BACKEND_PORT}" in script
