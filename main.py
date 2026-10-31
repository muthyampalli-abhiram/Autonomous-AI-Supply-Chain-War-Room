"""CLI entry point for Autonomous AI Supply Chain War Room."""

import sys
from pathlib import Path

# Ensure src/ is on the Python path
_src_dir = Path(__file__).resolve().parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from warroom.config import get_settings


def mask_key(key: str) -> str:
    """Mask an API key for safe display."""
    if not key:
        return "<empty>"
    if len(key) <= 6:
        return "*" * len(key)
    return f"{key[:3]}...{key[-3:]}"


def main() -> None:
    """Load and print configuration settings, then output health check status."""
    title = "Autonomous AI Supply Chain War Room"
    separator = "=" * 60

    print(separator)
    print(f"  {title}")
    print(separator)

    settings = get_settings()
    print("Configuration Settings:")
    print(f"  mock_llm:     {settings.mock_llm}")
    print(f"  llm_provider: {settings.llm_provider}")
    print(f"  llm_api_key:  {mask_key(settings.llm_api_key)}")
    print(f"  db_url:       {settings.db_url}")
    print(f"  random_seed:  {settings.random_seed}")
    print(f"  project_root: {settings.project_root}")
    print(f"  data_dir:     {settings.data_dir}")
    print(separator)
    print("Skeleton OK")


if __name__ == "__main__":
    main()
