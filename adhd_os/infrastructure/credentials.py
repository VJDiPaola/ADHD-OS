"""Secure credential storage using OS keyring with SQLite fallback."""

import logging
from typing import Optional

_SERVICE_NAME = "adhd-os"
_logger = logging.getLogger(__name__)

try:
    import keyring as _keyring

    _keyring.get_password(_SERVICE_NAME, "__probe__")
    _HAS_KEYRING = True
except Exception:
    _HAS_KEYRING = False
    _logger.debug("keyring unavailable; falling back to database storage for credentials")


def store_credential(key: str, value: str, *, db=None) -> None:
    if _HAS_KEYRING:
        _keyring.set_password(_SERVICE_NAME, key, value)
    elif db is not None:
        db.save_app_setting(key, value)


def load_credential(key: str, *, db=None) -> Optional[str]:
    if _HAS_KEYRING:
        value = _keyring.get_password(_SERVICE_NAME, key)
        if value:
            return value
    if db is not None:
        value = db.get_app_setting(key)
        if value:
            return str(value)
    return None


def delete_credential(key: str, *, db=None) -> None:
    if _HAS_KEYRING:
        try:
            _keyring.delete_password(_SERVICE_NAME, key)
        except Exception:
            pass
    if db is not None:
        db.delete_app_setting(key)
