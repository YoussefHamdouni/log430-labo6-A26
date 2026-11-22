"""
Saga Orchestrator
SPDX - License - Identifier: LGPL - 3.0 - or -later
Auteurs : Gabriel C. Ullmann, Fabio Petrillo, 2025
"""
import config
from flask import Flask, jsonify, request
from controllers.order_saga_controller import OrderSagaController
import os
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

app = Flask(__name__)

# --- Distributed tracing (Jaeger via OpenTelemetry) ---
resource = Resource.create({
    "service.name": "saga-orchestrator",
    "service.version": "1.0.0"
})
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)

# Jaeger reçoit les traces en OTLP/gRPC sur le port 4317 (hostname "jaeger" dans Docker)
otlp_exporter = OTLPSpanExporter(
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317"),
    insecure=True
)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))

# Instrumentation automatique : un span par requête Flask reçue,
# et propagation du contexte (en-tête traceparent) dans chaque appel requests sortant
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

@app.get('/health-check')
def health():
    """ Return OK if app is up and running """
    return jsonify({'status': 'ok'})

@app.post('/saga/order')
def saga_order():
    """ Start order saga """
    with tracer.start_as_current_span("saga-order") as span:
        order_saga_controller = OrderSagaController()
        result = order_saga_controller.run(request)
        span.set_attribute("saga.order_id", result["order_id"])
        span.set_attribute("saga.status", result["status"])
        span.set_attribute("saga.final_state", str(order_saga_controller.current_saga_state))

        if result["status"] == "OK":
            return jsonify(result), 200
        else:
            span.set_status(trace.Status(trace.StatusCode.ERROR, result["status"]))
            return jsonify(result), 500

# Start Flask app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config.FLASK_PORT)
