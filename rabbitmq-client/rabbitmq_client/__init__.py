"""
RabbitMQ Client Library

A shared library for RabbitMQ messaging across Aurora microservices.
"""

from .consumer import RabbitMQConsumer
from .producer import RabbitMQProducer

__version__ = "0.1.0"

__all__ = [
    "RabbitMQConsumer",
    "RabbitMQProducer",
]
