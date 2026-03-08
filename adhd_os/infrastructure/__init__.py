import importlib


def __getattr__(name):
    """Lazy-load infrastructure submodules for patch() and lightweight imports."""
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(name) from exc
