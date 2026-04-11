"""OpenTelemetry tracer and meter initialization, @traced decorator."""

import functools
import logging
from typing import Callable, Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.trace import StatusCode

from observability.config import ObservabilityConfig

logger = logging.getLogger(__name__)

_tracer: Optional[trace.Tracer] = None
_meter: Optional[metrics.Meter] = None
_initialized = False


def init_observability(config: Optional[ObservabilityConfig] = None) -> None:
    """Initialize OpenTelemetry tracing and metrics."""
    global _tracer, _meter, _initialized
    if _initialized:
        return

    config = config or ObservabilityConfig()
    if not config.enabled:
        logger.info("Observability disabled via config")
        _tracer = trace.get_tracer(config.service_name)
        _meter = metrics.get_meter(config.service_name)
        _initialized = True
        return

    resource = Resource.create({SERVICE_NAME: config.service_name})

    # Tracing
    tracer_provider = TracerProvider(resource=resource)
    try:
        span_exporter = OTLPSpanExporter(
            endpoint=config.otel_endpoint,
            insecure=config.otel_insecure,
        )
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    except Exception as e:
        logger.warning("Failed to connect OTLP trace exporter: %s", e)
    trace.set_tracer_provider(tracer_provider)

    # Metrics
    try:
        metric_exporter = OTLPMetricExporter(
            endpoint=config.otel_endpoint,
            insecure=config.otel_insecure,
        )
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter, export_interval_millis=15000,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    except Exception as e:
        logger.warning("Failed to connect OTLP metric exporter: %s", e)
        meter_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(meter_provider)

    _tracer = trace.get_tracer(config.service_name)
    _meter = metrics.get_meter(config.service_name)
    _initialized = True
    logger.info("Observability initialized: endpoint=%s", config.otel_endpoint)


def get_tracer() -> trace.Tracer:
    """Return the configured tracer, initializing with defaults if needed."""
    global _tracer
    if _tracer is None:
        init_observability()
    return _tracer


def get_meter() -> metrics.Meter:
    """Return the configured meter, initializing with defaults if needed."""
    global _meter
    if _meter is None:
        init_observability()
    return _meter


def traced(span_name: str, attributes: Optional[dict] = None) -> Callable:
    """Decorator that wraps a function in an OTEL span.

    Automatically records exceptions as span events and sets error status.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_status(StatusCode.ERROR, str(e))
                    span.record_exception(e)
                    raise
        return wrapper
    return decorator
