"""
core/error_handler.py

Centralized error handling for the AI Meeting Representative.
Provides a safe execution wrapper and a decorator to catch, log, and recover
from unexpected exceptions without crashing the thread.
"""

import functools
import traceback
import logging
from typing import Callable, Any

def safe_execute(logger: logging.Logger, func: Callable, *args, **kwargs) -> Any:
    """
    Executes a function safely. If an exception occurs, logs the full
    traceback to the provided logger, and returns None, allowing the host
    thread to continue execution.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(
            "Unhandled exception in safe_execute for %s: %s\n%s",
            func.__name__, e, traceback.format_exc()
        )
        return None

def handle_errors(logger: logging.Logger):
    """
    A decorator to wrap top-level entry points (like thread targets or event loops).
    Catches and logs any unhandled exceptions to prevent the thread from dying.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    "Unhandled exception in %s: %s\n%s",
                    func.__name__, e, traceback.format_exc()
                )
                return None
        return wrapper
    return decorator
