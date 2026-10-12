"""
RabbitMQ instrumentation for OpenTelemetry.
Adds trace context propagation to AMQP messages.
"""

import json
from typing import Dict, Any, Optional, Callable
from functools import wraps

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.context import attach, detach

from .telemetry import get_tracer

# Global propagator
propagator = TraceContextTextMapPropagator()


def inject_trace_context(properties: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inject trace context into AMQP message properties.
    
    Args:
        properties: AMQP message properties dict
    
    Returns:
        Updated properties with trace context
    """
    tracer = get_tracer()
    if not tracer:
        return properties
    
    # Create headers dict if not exists
    if 'headers' not in properties:
        properties['headers'] = {}
    
    # Inject trace context
    carrier = {}
    propagator.inject(carrier)
    
    # Add trace context to headers
    for key, value in carrier.items():
        properties['headers'][f'traceparent_{key}'] = value
    
    return properties


def extract_trace_context(properties: Dict[str, Any]) -> Optional[Any]:
    """
    Extract trace context from AMQP message properties and set as current.
    
    Args:
        properties: AMQP message properties dict
    
    Returns:
        Context token (use with detach()) or None
    """
    tracer = get_tracer()
    if not tracer:
        return None
    
    headers = properties.get('headers', {})
    
    # Extract trace context
    carrier = {}
    for key, value in headers.items():
        if key.startswith('traceparent_'):
            clean_key = key.replace('traceparent_', '')
            carrier[clean_key] = value
    
    if not carrier:
        return None
    
    # Extract and attach context
    context = propagator.extract(carrier)
    token = attach(context)
    
    return token


def instrument_rabbitmq_publish(publish_func: Callable) -> Callable:
    """
    Decorator to instrument RabbitMQ message publishing.
    
    Usage:
        @instrument_rabbitmq_publish
        def publish(self, queue, body, properties):
            ...
    """
    @wraps(publish_func)
    def wrapper(self, queue: str, body: Any, properties: Optional[Dict] = None, *args, **kwargs):
        tracer = get_tracer()
        
        if properties is None:
            properties = {}
        
        # Inject trace context
        properties = inject_trace_context(properties)
        
        # Create span
        if tracer:
            with tracer.start_as_current_span(
                "rabbitmq.publish",
                attributes={
                    "messaging.system": "rabbitmq",
                    "messaging.destination": queue,
                    "messaging.operation": "publish",
                }
            ):
                return publish_func(self, queue, body, properties, *args, **kwargs)
        else:
            return publish_func(self, queue, body, properties, *args, **kwargs)
    
    return wrapper


def instrument_rabbitmq_consume(consume_func: Callable) -> Callable:
    """
    Decorator to instrument RabbitMQ message consumption.
    
    Usage:
        @instrument_rabbitmq_consume
        def on_message(self, ch, method, properties, body):
            ...
    """
    @wraps(consume_func)
    def wrapper(self, ch, method, properties, body, *args, **kwargs):
        tracer = get_tracer()
        
        # Extract trace context
        token = extract_trace_context(properties.__dict__ if hasattr(properties, '__dict__') else {})
        
        try:
            # Create span
            if tracer:
                with tracer.start_as_current_span(
                    "rabbitmq.process",
                    attributes={
                        "messaging.system": "rabbitmq",
                        "messaging.source": method.routing_key if hasattr(method, 'routing_key') else "unknown",
                        "messaging.operation": "process",
                    }
                ):
                    return consume_func(self, ch, method, properties, body, *args, **kwargs)
            else:
                return consume_func(self, ch, method, properties, body, *args, **kwargs)
        finally:
            # Detach context
            if token:
                detach(token)
    
    return wrapper
