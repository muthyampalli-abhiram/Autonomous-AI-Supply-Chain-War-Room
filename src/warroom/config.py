"""Configuration module for Autonomous AI Supply Chain War Room."""

import os
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Locate project root (three levels up: config.py -> warroom -> src -> project_root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Load .env if present; no error if missing
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()


def _str_to_bool(val: str | bool | None, default: bool = True) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes", "on", "t")


def _str_to_int(val: str | int | None, default: int = 42) -> int:
    if val is None:
        return default
    if isinstance(val, int):
        return val
    try:
        return int(str(val).strip())
    except ValueError:
        return default


class Settings(BaseModel):
    """Pydantic model representing application configuration settings."""

    mock_llm: bool = Field(default=True, description="Whether to mock LLM calls")
    llm_provider: str = Field(default="mock", description="LLM provider name")
    llm_api_key: str = Field(default="", description="API key for LLM provider")
    db_url: str = Field(
        default="sqlite:///data/warroom.db", description="Database connection URL"
    )
    random_seed: int = Field(default=42, description="Random seed for data generation")
    project_root: Path = Field(
        default_factory=lambda: PROJECT_ROOT, description="Root directory of the project"
    )
    data_dir: Path = Field(
        default_factory=lambda: DATA_DIR, description="Directory for persistent data"
    )

    model_config = {"arbitrary_types_allowed": True}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance loaded from environment variables with defaults.

    Defaults work with NO .env file present.
    """
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)

    return Settings(
        mock_llm=_str_to_bool(os.getenv("MOCK_LLM", "true"), default=True),
        llm_provider=os.getenv("LLM_PROVIDER", "mock"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        db_url=os.getenv("DB_URL", "sqlite:///data/warroom.db"),
        random_seed=_str_to_int(os.getenv("RANDOM_SEED", "42"), default=42),
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
    )
