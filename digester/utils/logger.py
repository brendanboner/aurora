import logging


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Setup and return a configured logger."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Console handler
    handler = logging.StreamHandler()
    handler.setLevel(getattr(logging, level.upper()))
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Add handler if not already added
    if not logger.handlers:
        logger.addHandler(handler)
    
    return logger
