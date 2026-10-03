"""Unified logging configuration with persistent rotating file handlers and console output.

Stores logs in /app/data/logs (inside Docker volume) or ./logs (locally).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_log_dir() -> Path:
    """Return persistent log directory (/app/data/logs in container or ./logs locally)."""
    env_dir = os.environ.get("LOG_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    app_data = Path("/app/data")
    if app_data.exists() and os.access(app_data, os.W_OK):
        p = app_data / "logs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    local_p = PROJECT_ROOT / "logs"
    local_p.mkdir(parents=True, exist_ok=True)
    return local_p


def setup_logging(service_name: str = "voice-agent", log_level: int = logging.INFO) -> Path:
    """Configure root logger with both console and rotating file output.

    Returns the path to the active log file.
    """
    log_dir = get_log_dir()
    log_file = log_dir / f"{service_name}.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Prevent duplicate handlers on re-init
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    # Suppress duplicate handlers in child loggers like livekit
    for child_name in ("livekit", "livekit.agents", "livekit.plugins"):
        child = logging.getLogger(child_name)
        child.handlers.clear()
        child.propagate = True

    # 1. Console stream handler (single instance)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 2. Rotating file handler (10MB x 5 backups)
    try:
        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        console_handler.handle(
            logging.LogRecord(
                name="logging_config",
                level=logging.WARNING,
                pathname=__file__,
                lineno=65,
                msg=f"Could not open log file {log_file}: {e}",
                args=(),
                exc_info=None,
            )
        )

    return log_file


def read_logs(service_name: str = "agent", max_lines: int = 200) -> str:
    """Read the last N lines from the specified service log file."""
    log_dir = get_log_dir()
    log_file = log_dir / f"{service_name}.log"
    if not log_file.exists():
        # Fall back to voice-agent.log or backend.log if requested file not found
        fallback = log_dir / "voice-agent.log"
        if fallback.exists():
            log_file = fallback
        else:
            return f"No log file found at {log_file}."

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-max_lines:])
    except Exception as e:
        return f"Error reading log file {log_file}: {e}"
