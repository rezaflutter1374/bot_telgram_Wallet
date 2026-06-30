from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

db_operation_duration = Histogram(
    "db_operation_duration_seconds",
    "Database operation duration",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)

order_created_total = Counter("order_created_total", "Total orders created", ["side", "order_type"])
order_filled_total = Counter("order_filled_total", "Total orders filled", ["side"])
order_rejected_total = Counter("order_rejected_total", "Total orders rejected", ["reason"])
trade_executed_total = Counter("trade_executed_total", "Total trades executed")
settlement_total = Counter("settlement_total", "Total settlement runs", ["status"])
settlement_duration = Histogram(
    "settlement_duration_seconds",
    "Settlement execution duration",
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)
price_refresh_duration = Histogram(
    "price_refresh_duration_seconds",
    "Price refresh duration",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)
payment_approved_total = Counter("payment_approved_total", "Total payments approved", ["payment_type"])
payment_rejected_total = Counter("payment_rejected_total", "Total payments rejected", ["payment_type"])
notification_sent_total = Counter("notification_sent_total", "Total notifications sent", ["channel"])
user_registered_total = Counter("user_registered_total", "Total users registered")
rate_limit_hits_total = Counter("rate_limit_hits_total", "Total rate limit hits")
circuit_breaker_events = Counter("circuit_breaker_events_total", "Circuit breaker state changes", ["circuit", "state"])
dlq_entries_total = Counter("dlq_entries_total", "Dead letter queue entries", ["source"])

# Gauges for live monitoring
active_users_gauge = Gauge("active_users", "Number of active users")
open_orders_gauge = Gauge("open_orders", "Number of open orders")
pending_payments_gauge = Gauge("pending_payments", "Number of pending payment requests")
open_violations_gauge = Gauge("open_violations", "Number of open risk violations")
db_pool_size_gauge = Gauge("db_pool_size", "Database connection pool size")
redis_connected_gauge = Gauge("redis_connected", "Redis connection status (1=connected, 0=disconnected)")
price_stale_gauge = Gauge("price_stale", "Price stale status (1=stale, 0=fresh)")
circuit_breaker_gauge = Gauge("circuit_breaker_state", "Circuit breaker state (0=closed, 1=open, 2=half_open)", ["circuit"])
