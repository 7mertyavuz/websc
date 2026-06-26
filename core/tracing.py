"""
Katman 5: Dağıtık İzleme (Distributed Tracing - Jaeger / OpenTelemetry)
Sistemdeki darboğazları ve Celery -> API -> DB arası akışı milisaniye bazında izler.
"""
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from core.config import settings

def setup_tracing(service_name: str) -> None:
    # Zaten kuruluysa atla
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
        
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    
    # Jaeger OTLP HTTP alıcısına gönder
    exporter = OTLPSpanExporter(endpoint=settings.jaeger_endpoint)
    span_processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(span_processor)
    
    trace.set_tracer_provider(provider)
