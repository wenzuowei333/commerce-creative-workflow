from functools import lru_cache
from pathlib import Path
from pydantic import model_validator
from app.demo_safety import ensure_demo_database

ROOT = Path(__file__).resolve().parents[2]

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_name: str = "商品多模态创作工作台"
    app_base_path: str = "/image-studio"
    environment: str = "demo"
    database_url: str = "postgresql+psycopg://portfolio_demo:local-demo-only@127.0.0.1:25436/creative_demo"
    redis_url: str = "redis://127.0.0.1:26380/0"
    queue_mode: str = "dramatiq"
    media_backend: str = "local"
    media_root: str = str(ROOT / "runtime/media")
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_region: str = ""
    cos_bucket: str = ""
    cos_scheme: str = "https"
    session_backend: str = "redis"
    ai_mode: str = "mock"
    admin_username: str = "demo_admin"
    admin_password: str = "LocalDemo-2026!"
    session_secret: str = "portfolio-demo-only-session-value-2026"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = 86400
    login_attempt_limit: int = 5
    login_window_seconds: int = 300
    image_daily_limit: int = 200
    generation_concurrency: int = 2
    generation_lease_seconds: float = 12
    generation_heartbeat_seconds: float = 2
    demo_generation_delay_seconds: float = 0.5
    recovery_interval_seconds: float = 3
    backup_cos_prefix: str = "backups/image-studio"
    metrics_enabled: bool = True
    vision_model: str = "gpt-5.6-terra"
    prompt_model: str = "gpt-5.6-terra"
    image_model: str = "gpt-image-2"
    openai_compat_base_url: str = ""
    openai_compat_api_key: str = ""
    feature_live_provider: bool = False
    feature_cos_media: bool = False
    feature_image_revisions: bool = True
    feature_hd_finalize: bool = True
    feature_templates: bool = True

    @model_validator(mode="after")
    def validate_demo_targets(self):
        if self.environment != "demo":
            return self  # Retain upstream tests with explicitly supplied test settings.
        ensure_demo_database(self.database_url, "creative_demo", ROOT)
        if self.ai_mode != "mock" or self.media_backend != "local":
            raise ValueError("Demo candidate requires Mock AI and local media")
        if self.feature_live_provider or self.feature_cos_media:
            raise ValueError("Live provider and COS are disabled in demo mode")
        if self.openai_compat_api_key or self.openai_compat_base_url or self.cos_secret_id or self.cos_secret_key or self.cos_bucket or self.cos_region:
            raise ValueError("External credentials/endpoints are not accepted in demo mode")
        if Path(self.media_root).resolve() != (ROOT / "runtime/media").resolve():
            raise ValueError("Media must use this candidate's runtime/media directory")
        from urllib.parse import urlparse
        redis = urlparse(self.redis_url)
        if redis.scheme != "redis" or redis.hostname not in {"127.0.0.1", "localhost", "redis"} or redis.port not in {6379, 26380, 26381, 18379}:
            raise ValueError("Redis must point to the local demo service")
        if self.generation_lease_seconds <= 0 or not 0 < self.generation_heartbeat_seconds < self.generation_lease_seconds:
            raise ValueError("Heartbeat must be shorter than a positive lease")
        if not 0 <= self.demo_generation_delay_seconds <= 5:
            raise ValueError("Mock demo delay must be between zero and five seconds")
        return self

    def public_feature_flags(self) -> dict[str, bool]:
        return {
            "live_provider": self.feature_live_provider,
            "cos_media": self.feature_cos_media,
            "image_revisions": self.feature_image_revisions,
            "hd_finalize": self.feature_hd_finalize,
            "templates": self.feature_templates,
        }

    def feature_enabled(self, name: str) -> bool:
        flags = self.public_feature_flags()
        if name not in flags:
            raise ValueError(f"Unknown feature flag: {name}")
        return flags[name]

    def production_readiness_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.database_url.startswith("postgresql"):
            errors.append("PostgreSQL")
        if self.queue_mode != "dramatiq":
            errors.append("Dramatiq")
        if self.media_backend != "cos" or not all(
            [self.cos_secret_id, self.cos_secret_key, self.cos_region, self.cos_bucket]
        ):
            errors.append("COS")
        if self.session_backend != "redis":
            errors.append("Redis Session")
        if self.ai_mode != "compatible" or not all(
            [self.openai_compat_base_url, self.openai_compat_api_key]
        ):
            errors.append("AI Provider")
        if not self.session_cookie_secure:
            errors.append("Secure Cookie")
        if len(self.session_secret) < 32 or self.session_secret.startswith("development-"):
            errors.append("Session Secret")
        if self.admin_password == "change-me" or len(self.admin_password) < 12:
            errors.append("Admin Password")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
