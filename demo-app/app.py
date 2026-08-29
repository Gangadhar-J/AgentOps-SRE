import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# Setup Application Metadata
SERVICE_NAME = "demo-order-service"
POD_NAME = os.getenv("POD_NAME", "local-pod")
POD_NAMESPACE = os.getenv("POD_NAMESPACE", "demo")
NODE_NAME = os.getenv("NODE_NAME", "local-node")
FAILURE_MODE = os.getenv("FAILURE_MODE", "none").lower().strip()
CRASH_THRESHOLD = int(os.getenv("CRASH_THRESHOLD", "3"))

# Structured JSON Logger
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": SERVICE_NAME,
            "namespace": POD_NAMESPACE,
            "pod": POD_NAME,
            "node": NODE_NAME,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            log_obj["request_id"] = record.request_id
        if hasattr(record, "endpoint"):
            log_obj["endpoint"] = record.endpoint
        if hasattr(record, "status_code"):
            log_obj["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_obj["duration_ms"] = record.duration_ms
        if hasattr(record, "error_type"):
            log_obj["error_type"] = record.error_type
        if hasattr(record, "stack_trace"):
            log_obj["stack_trace"] = record.stack_trace
        if record.exc_info:
            log_obj["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("demo-app")
logger.setLevel(logging.INFO)
logger.handlers = [handler]
logger.propagate = False

app = Flask(__name__)

# Prometheus Metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests processed by endpoint and status",
    ["method", "endpoint", "status", "app"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint", "app"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
ORDERS_PROCESSED = Counter(
    "app_orders_processed_total",
    "Total orders processed",
    ["status", "item_type", "app"],
)
SYNTHETIC_MEMORY_GAUGE = Gauge(
    "app_memory_allocated_bytes",
    "Simulated memory allocated by the application for leak demonstration",
    ["app"],
)

# In-memory State
request_counter = 0
request_counter_lock = threading.Lock()
memory_leak_buffer = []
orders_db = []

# Background memory exhaustion worker if failure mode is active
def _memory_exhaustion_worker():
    global memory_leak_buffer
    logger.warning(
        "Resource exhaustion failure mode active: beginning memory leak simulation",
        extra={"endpoint": "background-worker"},
    )
    sys.stdout.flush()
    chunk_size = 20 * 1024 * 1024  # 20MB chunks
    allocated_total = 0
    while True:
        try:
            time.sleep(2)
            chunk = bytearray(chunk_size)
            for i in range(0, chunk_size, 4096):
                chunk[i] = 1
            memory_leak_buffer.append(chunk)
            allocated_total += chunk_size
            SYNTHETIC_MEMORY_GAUGE.labels(app="demo-app").set(allocated_total)
            logger.warning(
                f"Memory allocation leak running: allocated {allocated_total / (1024 * 1024):.1f} MB",
                extra={"endpoint": "background-worker"},
            )
            sys.stdout.flush()
        except MemoryError:
            logger.error(
                "Memory allocation failed: OOM condition reached",
                extra={"endpoint": "background-worker", "error_type": "MemoryError"},
            )
            sys.stdout.flush()
            break
        except Exception as e:
            logger.error(
                f"Unexpected error in memory leak worker: {str(e)}",
                extra={"endpoint": "background-worker"},
            )
            sys.stdout.flush()
            break

if FAILURE_MODE == "resource_exhaustion":
    t = threading.Thread(target=_memory_exhaustion_worker, daemon=True)
    t.start()


@app.before_request
def start_timer():
    g.start_time = time.time()
    g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))


@app.after_request
def record_metrics(response):
    if request.path != "/metrics":
        duration = time.time() - g.start_time
        endpoint = request.path
        method = request.method
        status_code = str(response.status_code)

        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status_code, app="demo-app").inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint, app="demo-app").observe(duration)

        logger.info(
            f"Request completed: {method} {endpoint} -> {status_code}",
            extra={
                "request_id": g.request_id,
                "endpoint": endpoint,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        sys.stdout.flush()
    response.headers["X-Request-ID"] = g.request_id
    return response


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": SERVICE_NAME,
        "pod": POD_NAME,
        "namespace": POD_NAMESPACE,
        "node": NODE_NAME,
        "failure_mode": FAILURE_MODE,
    }), 200


@app.route("/ready", methods=["GET"])
def ready():
    return jsonify({
        "status": "ready",
        "service": SERVICE_NAME,
        "failure_mode": FAILURE_MODE,
    }), 200


@app.route("/orders", methods=["GET"])
def list_orders():
    return jsonify({
        "total": len(orders_db),
        "orders": orders_db[-20:],
    }), 200


@app.route("/orders", methods=["POST"])
def create_order():
    global request_counter

    # Check for crashloop failure mode
    if FAILURE_MODE == "crashloop":
        with request_counter_lock:
            request_counter += 1
            current = request_counter
        if current >= CRASH_THRESHOLD:
            logger.critical(
                f"FATAL: Unhandled segmentation fault / panic triggered by threshold ({current}/{CRASH_THRESHOLD})",
                extra={
                    "request_id": g.request_id,
                    "endpoint": "/orders",
                    "error_type": "FatalProcessCrash",
                    "stack_trace": "Traceback (most recent call last):\n  File \"app.py\", line 185, in create_order\n    raise SystemExit('Fatal container panic')",
                },
            )
            sys.stdout.flush()
            time.sleep(0.1)
            try:
                os.kill(os.getppid(), signal.SIGKILL)
            except Exception:
                pass
            os.kill(os.getpid(), signal.SIGKILL)

    # Check for high error rate failure mode
    if FAILURE_MODE == "high_error_rate":
        with request_counter_lock:
            request_counter += 1
            is_error = (request_counter % 2 == 0)
        if is_error:
            ORDERS_PROCESSED.labels(status="failed", item_type="unknown", app="demo-app").inc()
            logger.error(
                "DatabaseConnectionTimeout: Connection to primary postgres-replica-0 timed out after 5000ms",
                extra={
                    "request_id": g.request_id,
                    "endpoint": "/orders",
                    "status_code": 500,
                    "error_type": "DatabaseConnectionTimeout",
                    "stack_trace": "Traceback (most recent call last):\n  File \"app.py\", line 205, in create_order\n  ConnectionTimeoutError: Failed to acquire connection from pool [pool_size=10, active=10]",
                },
            )
            sys.stdout.flush()
            return jsonify({
                "error": "InternalServerError",
                "message": "Database connection timeout while committing transaction",
                "request_id": g.request_id,
            }), 500

    # Normal successful order creation
    data = request.get_json(silent=True) or {}
    item_type = data.get("item", "standard-widget")
    amount = data.get("amount", 1)

    order = {
        "order_id": str(uuid.uuid4()),
        "item": item_type,
        "amount": amount,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processed_by_pod": POD_NAME,
    }
    orders_db.append(order)
    ORDERS_PROCESSED.labels(status="success", item_type=item_type, app="demo-app").inc()

    logger.info(
        f"Order {order['order_id']} created successfully for item '{item_type}'",
        extra={
            "request_id": g.request_id,
            "endpoint": "/orders",
            "status_code": 201,
        },
    )
    sys.stdout.flush()
    return jsonify(order), 201


@app.route("/metrics", methods=["GET"])
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
