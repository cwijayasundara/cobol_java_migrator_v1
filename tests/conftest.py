from pathlib import Path
import pytest

CARDDEMO = Path(
    "/Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0"
    "/source_code_to_analyse/aws-mf-mod-carddemo"
)

@pytest.fixture
def carddemo_root() -> Path:
    if not CARDDEMO.exists():
        pytest.skip(f"CardDemo source not present at {CARDDEMO}")
    return CARDDEMO
