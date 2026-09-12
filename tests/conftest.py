import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CORPUS = ROOT / "tests" / "corpus" / "step"
DEGRADED = ROOT / "tests" / "corpus" / "step_degraded"


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    if not CORPUS.exists() or not list(CORPUS.glob("*.step")):
        pytest.skip("corpus absent : lancer 'python tools/make_corpus.py'")
    return CORPUS


@pytest.fixture(scope="session")
def degraded_dir() -> Path:
    if not DEGRADED.exists() or not list(DEGRADED.glob("*.step")):
        pytest.skip("corpus degrade absent : lancer "
                    "'python tools/make_degraded_corpus.py'")
    return DEGRADED


@pytest.fixture(scope="session")
def manifest():
    import json
    p = ROOT / "tests" / "corpus" / "manifest.json"
    if not p.exists():
        pytest.skip("manifeste absent : lancer 'python tools/make_corpus.py'")
    return json.loads(p.read_text())


@pytest.fixture(scope="session")
def tool():
    from xyzac.tool_model import build_endmill
    return build_endmill("EM6", 6.0, 20.0, stickout=45.0, holder_type="ER16")


@pytest.fixture(scope="session")
def machine():
    from xyzac.machine_model import default_xyzac_kit
    return default_xyzac_kit()
