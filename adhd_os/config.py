import os
import logging
from enum import Enum

_logger = logging.getLogger(__name__)

DEFAULT_FAST_MODEL = "gemini/gemini-3-flash-preview"


class ModelMode(Enum):
    PRODUCTION = "production"      # Optimized for cost/latency
    QUALITY = "quality"            # Optimized for nuance
    AB_TEST = "ab_test"            # Random selection for testing


# Primary model registry
MODELS = {
    "orchestrator": "gemini/gemini-3-flash-preview",
    "decomposer_quality": "anthropic/claude-sonnet-4-6",
    "decomposer_fast": "gemini/gemini-3-flash-preview",
    "emotional": "anthropic/claude-sonnet-4-6",
    "temporal": "gemini/gemini-3-flash-preview",
    "motivation": "gemini/gemini-3-flash-preview",
    "pattern_analysis": "gemini/gemini-3-flash-preview",
    "reflector_agent": "gemini/gemini-3-flash-preview",
}

# Fallback models — used when the primary provider is unavailable.
FALLBACK_MODELS = {
    "emotional": "gemini/gemini-3-flash-preview",
    "decomposer_quality": "gemini/gemini-3-flash-preview",
}


def get_model(role: str, mode: ModelMode = ModelMode.PRODUCTION) -> str:
    """Returns appropriate model based on role and mode."""
    if mode == ModelMode.AB_TEST and role == "decomposer":
        import random
        return random.choice([MODELS["decomposer_quality"], MODELS["decomposer_fast"]])
    elif mode == ModelMode.QUALITY and role == "decomposer":
        return MODELS["decomposer_quality"]
    elif role == "decomposer":
        return MODELS["decomposer_fast"]
    return MODELS.get(role, DEFAULT_FAST_MODEL)


def get_fallback_model(role: str) -> str:
    """Returns the fallback model for a role, or the default fast model."""
    return FALLBACK_MODELS.get(role, DEFAULT_FAST_MODEL)

_mode_raw = os.environ.get("ADHD_OS_MODEL_MODE", "production")
try:
    MODEL_MODE = ModelMode(_mode_raw)
except ValueError:
    import logging
    logging.getLogger(__name__).warning(
        "Unknown ADHD_OS_MODEL_MODE '%s', falling back to 'production'", _mode_raw
    )
    MODEL_MODE = ModelMode.PRODUCTION
