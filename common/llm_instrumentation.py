"""
LLM instrumentation for OpenTelemetry.
Wraps Azure OpenAI calls to add tracing and metrics.
"""

import time
import os
from typing import Optional, Dict, Any, Callable
from functools import wraps

from opentelemetry.trace import Status, StatusCode

from .telemetry import get_tracer, get_meter, hash_text


def instrument_llm_call(
    prompt_type: str,
    model_provider: str = "azure_openai",
):
    """
    Decorator to instrument LLM API calls.
    
    Args:
        prompt_type: Type of prompt (e.g., 'query_parse', 'summarize', 'extract', 'generate')
        model_provider: LLM provider name
    
    Usage:
        @instrument_llm_call(prompt_type="query_parse")
        def parse_query(self, query: str):
            response = self.client.chat.completions.create(...)
            return response
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return _execute_llm_with_instrumentation(
                func, args, kwargs, prompt_type, model_provider
            )
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await _execute_llm_with_instrumentation_async(
                func, args, kwargs, prompt_type, model_provider
            )
        
        # Return appropriate wrapper based on whether function is async
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return wrapper
    
    return decorator


def _execute_llm_with_instrumentation(
    func: Callable,
    args: tuple,
    kwargs: dict,
    prompt_type: str,
    model_provider: str,
) -> Any:
    """Execute LLM call with instrumentation (sync)."""
    
    tracer = get_tracer()
    meter = get_meter()
    
    # Create metrics
    if meter:
        request_counter = meter.create_counter(
            "llm.request.count",
            description="Number of LLM requests",
            unit="1",
        )
        duration_histogram = meter.create_histogram(
            "llm.request.duration_ms",
            description="LLM request duration",
            unit="ms",
        )
        prompt_tokens_counter = meter.create_counter(
            "llm.tokens.prompt",
            description="Number of prompt tokens",
            unit="1",
        )
        completion_tokens_counter = meter.create_counter(
            "llm.tokens.completion",
            description="Number of completion tokens",
            unit="1",
        )
        total_tokens_counter = meter.create_counter(
            "llm.tokens.total",
            description="Total number of tokens",
            unit="1",
        )
    
    start_time = time.time()
    
    # Prepare span attributes
    attributes = {
        "llm.provider": model_provider,
        "llm.prompt_type": prompt_type,
    }
    
    if tracer:
        with tracer.start_as_current_span("llm.completion", attributes=attributes) as span:
            try:
                result = func(*args, **kwargs)
                
                # Extract metrics from response
                metrics = _extract_llm_metrics(result, span, attributes)
                
                # Record metrics
                duration_ms = (time.time() - start_time) * 1000
                if meter and metrics:
                    metric_attrs = {
                        "llm.model": metrics.get("model", "unknown"),
                        "llm.provider": model_provider,
                        "llm.prompt_type": prompt_type,
                    }
                    request_counter.add(1, metric_attrs)
                    duration_histogram.record(duration_ms, metric_attrs)
                    
                    if metrics.get("prompt_tokens"):
                        prompt_tokens_counter.add(metrics["prompt_tokens"], metric_attrs)
                    if metrics.get("completion_tokens"):
                        completion_tokens_counter.add(metrics["completion_tokens"], metric_attrs)
                    if metrics.get("total_tokens"):
                        total_tokens_counter.add(metrics["total_tokens"], metric_attrs)
                
                span.set_status(Status(StatusCode.OK))
                return result
                
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                
                # Record error metric
                if meter:
                    request_counter.add(1, {
                        "llm.provider": model_provider,
                        "llm.prompt_type": prompt_type,
                        "error": "true",
                    })
                
                raise
    else:
        # No tracer, execute without tracing
        result = func(*args, **kwargs)
        
        # Still record metrics if available
        if meter:
            metrics = _extract_llm_metrics(result)
            duration_ms = (time.time() - start_time) * 1000
            metric_attrs = {
                "llm.model": metrics.get("model", "unknown"),
                "llm.provider": model_provider,
                "llm.prompt_type": prompt_type,
            }
            request_counter.add(1, metric_attrs)
            duration_histogram.record(duration_ms, metric_attrs)
            
            if metrics.get("prompt_tokens"):
                prompt_tokens_counter.add(metrics["prompt_tokens"], metric_attrs)
            if metrics.get("completion_tokens"):
                completion_tokens_counter.add(metrics["completion_tokens"], metric_attrs)
            if metrics.get("total_tokens"):
                total_tokens_counter.add(metrics["total_tokens"], metric_attrs)
        
        return result


async def _execute_llm_with_instrumentation_async(
    func: Callable,
    args: tuple,
    kwargs: dict,
    prompt_type: str,
    model_provider: str,
) -> Any:
    """Execute LLM call with instrumentation (async)."""
    
    tracer = get_tracer()
    meter = get_meter()
    
    # Create metrics
    if meter:
        request_counter = meter.create_counter(
            "llm.request.count",
            description="Number of LLM requests",
            unit="1",
        )
        duration_histogram = meter.create_histogram(
            "llm.request.duration_ms",
            description="LLM request duration",
            unit="ms",
        )
        prompt_tokens_counter = meter.create_counter(
            "llm.tokens.prompt",
            description="Number of prompt tokens",
            unit="1",
        )
        completion_tokens_counter = meter.create_counter(
            "llm.tokens.completion",
            description="Number of completion tokens",
            unit="1",
        )
        total_tokens_counter = meter.create_counter(
            "llm.tokens.total",
            description="Total number of tokens",
            unit="1",
        )
    
    start_time = time.time()
    
    attributes = {
        "llm.provider": model_provider,
        "llm.prompt_type": prompt_type,
    }
    
    if tracer:
        with tracer.start_as_current_span("llm.completion", attributes=attributes) as span:
            try:
                result = await func(*args, **kwargs)
                
                metrics = _extract_llm_metrics(result, span, attributes)
                
                duration_ms = (time.time() - start_time) * 1000
                if meter and metrics:
                    metric_attrs = {
                        "llm.model": metrics.get("model", "unknown"),
                        "llm.provider": model_provider,
                        "llm.prompt_type": prompt_type,
                    }
                    request_counter.add(1, metric_attrs)
                    duration_histogram.record(duration_ms, metric_attrs)
                    
                    if metrics.get("prompt_tokens"):
                        prompt_tokens_counter.add(metrics["prompt_tokens"], metric_attrs)
                    if metrics.get("completion_tokens"):
                        completion_tokens_counter.add(metrics["completion_tokens"], metric_attrs)
                    if metrics.get("total_tokens"):
                        total_tokens_counter.add(metrics["total_tokens"], metric_attrs)
                
                span.set_status(Status(StatusCode.OK))
                return result
                
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                
                if meter:
                    request_counter.add(1, {
                        "llm.provider": model_provider,
                        "llm.prompt_type": prompt_type,
                        "error": "true",
                    })
                
                raise
    else:
        result = await func(*args, **kwargs)
        
        if meter:
            metrics = _extract_llm_metrics(result)
            duration_ms = (time.time() - start_time) * 1000
            metric_attrs = {
                "llm.model": metrics.get("model", "unknown"),
                "llm.provider": model_provider,
                "llm.prompt_type": prompt_type,
            }
            request_counter.add(1, metric_attrs)
            duration_histogram.record(duration_ms, metric_attrs)
            
            if metrics.get("prompt_tokens"):
                prompt_tokens_counter.add(metrics["prompt_tokens"], metric_attrs)
            if metrics.get("completion_tokens"):
                completion_tokens_counter.add(metrics["completion_tokens"], metric_attrs)
            if metrics.get("total_tokens"):
                total_tokens_counter.add(metrics["total_tokens"], metric_attrs)
        
        return result


def _extract_llm_metrics(result: Any, span=None, attributes=None) -> Dict[str, Any]:
    """Extract metrics from Azure OpenAI response."""
    metrics = {}
    
    try:
        # Azure OpenAI response structure
        if hasattr(result, 'usage'):
            usage = result.usage
            metrics["prompt_tokens"] = getattr(usage, 'prompt_tokens', 0)
            metrics["completion_tokens"] = getattr(usage, 'completion_tokens', 0)
            metrics["total_tokens"] = getattr(usage, 'total_tokens', 0)
        
        if hasattr(result, 'model'):
            metrics["model"] = result.model
        
        # Add to span if available
        if span and metrics:
            span.set_attribute("llm.model", metrics.get("model", "unknown"))
            span.set_attribute("llm.tokens.prompt", metrics.get("prompt_tokens", 0))
            span.set_attribute("llm.tokens.completion", metrics.get("completion_tokens", 0))
            span.set_attribute("llm.tokens.total", metrics.get("total_tokens", 0))
    
    except Exception as e:
        # Don't fail on metrics extraction
        if span:
            span.add_event("metrics_extraction_failed", {"error": str(e)})
    
    return metrics


def create_llm_span_manually(
    tracer,
    prompt_type: str,
    model: str,
    model_provider: str = "azure_openai",
):
    """
    Create an LLM span manually for wrapping existing code.
    
    Usage:
        with create_llm_span_manually(tracer, "query_parse", "gpt-4") as span:
            response = client.chat.completions.create(...)
            # Update span with metrics
            span.set_attribute("llm.tokens.total", response.usage.total_tokens)
    """
    if not tracer:
        from contextlib import nullcontext
        return nullcontext()
    
    return tracer.start_as_current_span(
        "llm.completion",
        attributes={
            "llm.provider": model_provider,
            "llm.prompt_type": prompt_type,
            "llm.model": model,
        }
    )
