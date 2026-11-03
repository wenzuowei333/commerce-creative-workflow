from app.core.errors import AppError


def test_app_error_has_safe_public_shape():
    error = AppError(
        code="provider_rate_limited",
        message="模型服务繁忙，请稍后重试",
        retryable=True,
        status_code=429,
        details={"retry_after": 30},
    )

    payload = error.to_payload("req-123")

    assert payload == {
        "error": {
            "code": "provider_rate_limited",
            "message": "模型服务繁忙，请稍后重试",
            "retryable": True,
            "request_id": "req-123",
            "details": {"retry_after": 30},
        }
    }
    assert "traceback" not in str(payload).lower()
