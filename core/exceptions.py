# core/exceptions.py — Centralized Exception Classes
# ============================================================
# Every module should fail safely using these exception types.
# ============================================================


class TraderError(Exception):
    """Base exception for all trading system errors."""
    pass


class DataFetchError(TraderError):
    """Failed to fetch market data."""
    pass


class DataValidationError(TraderError):
    """Market data failed quality checks."""
    pass


class AnalysisError(TraderError):
    """Analysis pipeline failed."""
    pass


class RiskError(TraderError):
    """Risk engine rejected the trade."""
    pass


class ExecutionError(TraderError):
    """Trade execution failed."""
    pass


class BrokerConnectionError(TraderError):
    """MT5 broker connection failed."""
    pass


class LLMError(TraderError):
    """AI/LLM analysis failed."""
    pass


class CircuitBreakerError(TraderError):
    """Trading halted by circuit breaker."""
    pass


class ConfigurationError(TraderError):
    """Invalid configuration detected."""
    pass


class TraderMemoryError(TraderError):
    """Memory/database operation failed."""
    pass

# Backward alias — avoid shadowing Python's built-in MemoryError
MemoryError = TraderMemoryError


def safe_execute(func, error_type=TraderError, fallback=None, module_name="unknown"):
    """Execute a function safely, catching and logging any exceptions."""
    from utils.logger import get_logger
    log = get_logger(module_name)
    try:
        return func()
    except Exception as e:
        log.error(f"[{module_name}] {error_type.__name__}: {e}", exc_info=True)
        if fallback is not None:
            return fallback
        raise error_type(str(e)) from e
