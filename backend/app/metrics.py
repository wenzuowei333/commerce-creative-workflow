from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "image_studio_http_requests_total",
    "HTTP requests handled by the image studio",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "image_studio_http_request_duration_seconds",
    "HTTP request duration",
    ("method", "route"),
)
