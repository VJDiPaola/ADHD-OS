import os

from adhd_os.infrastructure import database as database_module

GOOGLE_API_KEY_SETTING = "google_api_key"
ANTHROPIC_API_KEY_SETTING = "anthropic_api_key"
MODEL_MODE_SETTING = "model_mode"


def apply_saved_environment_settings(db=None):
    """Loads persisted local settings into environment variables for the next launch."""
    db = db or database_module.DB

    if not os.environ.get("GOOGLE_API_KEY"):
        google_api_key = db.get_app_setting(GOOGLE_API_KEY_SETTING)
        if google_api_key:
            os.environ["GOOGLE_API_KEY"] = str(google_api_key)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        anthropic_api_key = db.get_app_setting(ANTHROPIC_API_KEY_SETTING)
        if anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = str(anthropic_api_key)

    if not os.environ.get("ADHD_OS_MODEL_MODE"):
        model_mode = db.get_app_setting(MODEL_MODE_SETTING)
        if model_mode:
            os.environ["ADHD_OS_MODEL_MODE"] = str(model_mode)
