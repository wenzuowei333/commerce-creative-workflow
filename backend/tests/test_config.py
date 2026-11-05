from app.config import Settings


def test_settings_use_image_studio_defaults(monkeypatch):
    monkeypatch.delenv("APP_BASE_PATH", raising=False)
    monkeypatch.delenv("IMAGE_DAILY_LIMIT", raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_name == "商品多模态创作工作台"
    assert settings.app_base_path == "/image-studio"
    assert settings.image_daily_limit == 200
    assert settings.vision_model == "gpt-5.6-terra"
    assert settings.image_model == "gpt-image-2"
    assert settings.public_feature_flags() == {
        "live_provider": False,
        "cos_media": False,
        "image_revisions": True,
        "hd_finalize": True,
        "templates": True,
    }


def test_feature_flags_can_be_disabled_independently():
    settings = Settings(
        _env_file=None,
        feature_image_revisions=False,
        feature_templates=False,
    )

    assert settings.feature_enabled("image_revisions") is False
    assert settings.feature_enabled("templates") is False
    assert settings.feature_enabled("hd_finalize") is True


def test_production_requires_external_services():
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="sqlite:///local.db",
        queue_mode="inline",
        media_backend="local",
        session_backend="memory",
        admin_password="change-me",
    )

    errors = settings.production_readiness_errors()

    assert "PostgreSQL" in errors
    assert "Dramatiq" in errors
    assert "COS" in errors
    assert "Redis Session" in errors
    assert "AI Provider" in errors
    assert "Secure Cookie" in errors
    assert "Admin Password" in errors


def test_production_is_ready_with_complete_external_configuration():
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://user:password@postgres/image_studio",
        queue_mode="dramatiq",
        media_backend="cos",
        cos_secret_id="cos-id",
        cos_secret_key="cos-key",
        cos_region="ap-guangzhou",
        cos_bucket="private-bucket",
        session_backend="redis",
        session_secret="a-secure-session-secret-with-more-than-32-chars",
        session_cookie_secure=True,
        admin_password="a-secure-admin-password",
        ai_mode="compatible",
        openai_compat_base_url="https://gateway.example/v1",
        openai_compat_api_key="provider-key",
    )

    assert settings.production_readiness_errors() == []
