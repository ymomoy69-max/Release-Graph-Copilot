"""Load .env then application configuration from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    candidates = (
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    )
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = val
        break


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = "ReleaseGraph Copilot"
    environment: str = "development"
    debug: bool = True
    database_url: str = "sqlite:///./data/releasegraph.db"
    jwt_secret: str = "dev-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    )
    demo_services_url: str = "http://localhost:8081"
    request_id_header: str = "X-Request-Id"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-20b"

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        groq_key = os.getenv("GROQ_API_KEY") or os.getenv("RG_AI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        groq_base = (
            os.getenv("GROQ_BASE_URL")
            or os.getenv("RG_AI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.groq.com/openai/v1"
        )
        if groq_key.startswith("gsk_") and "openai.com" in groq_base:
            groq_base = "https://api.groq.com/openai/v1"
        model = os.getenv("RG_AI_MODEL") or os.getenv("GROQ_MODEL") or os.getenv("OPENAI_MODEL") or "openai/gpt-oss-20b"
        return cls(
            environment=os.getenv("ENVIRONMENT", "development"),
            debug=os.getenv("DEBUG", "true").lower() in ("1", "true", "yes"),
            database_url=os.getenv(
                "DATABASE_URL",
                "sqlite:///./data/releasegraph.db",
            ),
            jwt_secret=os.getenv("JWT_SECRET", "dev-change-me-in-production"),
            access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24))),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            demo_services_url=os.getenv("DEMO_SERVICES_URL", "http://localhost:8081"),
            groq_api_key=groq_key,
            groq_base_url=groq_base.rstrip("/"),
            groq_model=model,
        )


settings = Settings.from_env()
