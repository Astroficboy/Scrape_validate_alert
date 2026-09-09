import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.config import load_config


@pytest.fixture
def config():
    return load_config()
