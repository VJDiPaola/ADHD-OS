import logging
import json
import sys
import os
from datetime import datetime
from typing import Any, Dict

class JsonFormatter(logging.Formatter):
    """Formats logs as JSON lines."""
    def format(self, record):
        log_obj = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if hasattr(record, "props"):
            log_obj.update(record.props)
        
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_obj)

def setup_logging(log_file: str = "logs/adhd_os.jsonl"):
    """Configures structured logging to file and pretty print to console."""
    
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # File Handler (JSONL)
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(file_handler)
    
    # Console Handler (Human Readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | %(message)s'
    ))
    root_logger.addHandler(console_handler)

    return logging.getLogger("adhd_os")

# Lazy logger — initialized on first use or explicit call from main.
_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    """Return the application logger, initializing on first call."""
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger


# Backwards-compatible module-level alias (lazy property via __getattr__).
def __getattr__(name: str):
    if name == "logger":
        return get_logger()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
