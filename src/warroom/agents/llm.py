"""LLM narration helper for War Room agents."""

from __future__ import annotations

import logging
from typing import Any
from warroom.config import get_settings

logger = logging.getLogger(__name__)


def narrate(role: str, facts: dict[str, Any], fallback: str) -> str:
    """Generate a narrative summary for an agent role, falling back to a deterministic string."""
    settings = get_settings()
    if settings.mock_llm:
        return fallback

    try:
        if settings.llm_provider == "mock" or not settings.llm_api_key:
            return fallback

        # If an external LLM provider is connected in the future, invoke it here
        return fallback
    except Exception as exc:
        logger.warning("LLM narration failed for role '%s': %s", role, exc)
        return fallback
