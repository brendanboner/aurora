"""Oracle Service - Custom exceptions."""


class OracleError(Exception):
    """Base exception for Oracle service errors."""
    pass


class LLMTimeoutError(OracleError):
    """Raised when an LLM call times out."""
    pass


class LLMError(OracleError):
    """Raised when an LLM call fails for non-timeout reasons."""
    pass
