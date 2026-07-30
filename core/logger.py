"""
core/logger.py

Centralized logging for the AI Meeting Representative.

On first import this module:
  1. Creates  logs/YYYY-MM-DD_HH-MM-SS/  inside the project root.
  2. Opens a RotatingFileHandler for each sub-system log file.
  3. Attaches a shared error.log handler (ERROR+) to every logger.
  4. Attaches a console StreamHandler (ERROR+) so critical failures
     appear on screen in addition to being written to files.

Existing print() statements throughout the codebase are preserved
unchanged.  These loggers add parallel structured output.

If the log directory cannot be created the module falls back to
console-only logging and emits a single warning — it never raises.

Thread safety: Python's logging module is inherently thread-safe.
No extra locks are introduced.
"""

import logging
import logging.handlers
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_LOG_DIR: str | None = None          # set once during _init()
_error_file_handler: logging.Handler | None = None   # shared across loggers
_console_error_handler: logging.StreamHandler | None = None  # ERROR+ to stdout


# ---------------------------------------------------------------------------
# Initialisation  (runs once at import time)
# ---------------------------------------------------------------------------

def _init() -> None:
    global _LOG_DIR, _error_file_handler, _console_error_handler

    # Resolve project root (two levels above this file: core/ -> project root)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target_dir = os.path.join(project_root, "logs", ts)

    try:
        os.makedirs(target_dir, exist_ok=True)
        _LOG_DIR = target_dir
    except Exception as exc:                                    # pragma: no cover
        print(f"[logger] WARNING: Could not create log directory '{target_dir}': {exc}. "
              "Continuing with console-only logging.")
        _LOG_DIR = None

    _fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Shared error.log handler (ERROR+) — opened once, attached to every logger
    if _LOG_DIR is not None:
        try:
            error_path = os.path.join(_LOG_DIR, "error.log")
            _error_file_handler = logging.handlers.RotatingFileHandler(
                error_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            _error_file_handler.setLevel(logging.ERROR)
            _error_file_handler.setFormatter(_fmt)
        except Exception as exc:                                # pragma: no cover
            print(f"[logger] WARNING: Could not open error.log: {exc}")
            _error_file_handler = None

    # Shared console handler for ERROR+ (keeps existing print() output intact;
    # this only adds structured ERROR/CRITICAL lines to the console)
    _console_error_handler = logging.StreamHandler()
    _console_error_handler.setLevel(logging.ERROR)
    _console_error_handler.setFormatter(_fmt)


_init()


# ---------------------------------------------------------------------------
# Internal factory
# ---------------------------------------------------------------------------

def _make_logger(name: str, filename: str) -> logging.Logger:
    """
    Return a named logger, creating it on first call.

    Each logger gets:
      - A RotatingFileHandler writing to  logs/<ts>/<filename>  (DEBUG+)
      - The shared RotatingFileHandler writing to  error.log      (ERROR+)
      - A StreamHandler writing to stderr                          (ERROR+)

    propagate=False prevents duplicate output via the root logger.
    """
    logger = logging.getLogger(f"voa.{name}")

    if logger.handlers:          # already configured — idempotent
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    _fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Per-module file handler
    if _LOG_DIR is not None:
        try:
            path = os.path.join(_LOG_DIR, filename)
            fh = logging.handlers.RotatingFileHandler(
                path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(_fmt)
            logger.addHandler(fh)
        except Exception as exc:                                # pragma: no cover
            print(f"[logger] WARNING: Could not open {filename}: {exc}")

    # Shared error.log handler
    if _error_file_handler is not None:
        logger.addHandler(_error_file_handler)

    # Console ERROR+ handler
    if _console_error_handler is not None:
        logger.addHandler(_console_error_handler)

    return logger


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_app_logger() -> logging.Logger:
    """General application logger — startup, shutdown, warnings."""
    return _make_logger("app", "app.log")


def get_asr_logger() -> logging.Logger:
    """ASR logger — transcription latency, confidence, text."""
    return _make_logger("asr", "asr.log")


def get_llm_logger() -> logging.Logger:
    """LLM logger — requests, first-token latency, total latency, failures."""
    return _make_logger("llm", "llm.log")


def get_tts_logger() -> logging.Logger:
    """TTS logger — synthesis time, playback time, total latency."""
    return _make_logger("tts", "tts.log")


def get_retrieval_logger() -> logging.Logger:
    """Retrieval logger — query, retrieved memories, similarity scores."""
    return _make_logger("retrieval", "retrieval.log")


def get_events_logger() -> logging.Logger:
    """EventBus logger — publish/subscribe, subjects, payload summaries."""
    return _make_logger("events", "events.log")


def get_performance_logger() -> logging.Logger:
    """Performance logger — timing metrics for every pipeline stage."""
    return _make_logger("performance", "performance.log")


def get_error_logger() -> logging.Logger:
    """
    Dedicated error/traceback logger.

    Writes to error.log and appears on the console.
    Use this for unexpected exceptions and full tracebacks.
    """
    return _make_logger("error", "error.log")


def get_log_dir() -> str | None:
    """Return the current session log directory path, or None if unavailable."""
    return _LOG_DIR
