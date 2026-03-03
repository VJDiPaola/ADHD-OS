import os
from enum import Enum

class ModelMode(Enum):
    PRODUCTION = "production"      # Optimized for cost/latency
    QUALITY = "quality"            # Optimized for nuance
    AB_TEST = "ab_test"            # Random selection for testing

# Model registry with fallbacks
MODELS = {
    "orchestrator": "gemini/gemini-3-flash-preview",
    "decomposer_quality": "anthropic/claude-sonnet-4-6",
    "decomposer_fast": "gemini/gemini-3-flash-preview",
    "emotional": "anthropic/claude-sonnet-4-6",
    "temporal": "gemini/gemini-3-flash-preview",
    "motivation": "gemini/gemini-3-flash-preview",
    "pattern_analysis": "gemini/gemini-3-flash-preview",
    "reflector_agent": "gemini/gemini-3-flash-preview", # Added Reflector
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
    return MODELS.get(role, "gemini/gemini-3-flash-preview")

_mode_raw = os.environ.get("ADHD_OS_MODEL_MODE", "production")
try:
    MODEL_MODE = ModelMode(_mode_raw)
except ValueError:
    import logging
    logging.getLogger(__name__).warning(
        "Unknown ADHD_OS_MODEL_MODE '%s', falling back to 'production'", _mode_raw
    )
    MODEL_MODE = ModelMode.PRODUCTION
