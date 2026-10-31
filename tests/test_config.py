"""Unit tests for warroom configuration."""

import sys
from pathlib import Path

# Ensure src/ is on the Python path
_src_dir = Path(__file__).resolve().parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from warroom.config import get_settings


def test_get_settings_defaults():
    """Verify get_settings() returns default values when no environment overrides are set."""
    settings = get_settings()
    assert settings.mock_llm is True
    assert "sqlite" in settings.db_url
    assert settings.llm_provider == "mock"
    assert settings.random_seed == 42
    assert isinstance(settings.project_root, Path)
    assert isinstance(settings.data_dir, Path)
    assert settings.project_root.exists()
