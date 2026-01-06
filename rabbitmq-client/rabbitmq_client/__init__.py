"""
RabbitMQ Client Library

A shared library for RabbitMQ messaging across Aurora microservices.
"""

from .consumer_old import RabbitMQConsumer  # Legacy sync consumer
from .async_consumer import AsyncRabbitMQConsumer  # New async consumer
from .producer import RabbitMQProducer

__version__ = "0.2.0"

__all__ = [
    "RabbitMQConsumer",  # Legacy sync
    "AsyncRabbitMQConsumer",  # New async
    "RabbitMQProducer",
]
