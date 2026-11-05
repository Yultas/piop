import json
import os
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent

INSECURE_SECRETS = {"", "eink_super_secret_key_change_in_production_123456", "change_this_to_a_random_32_byte_string_for_production", "eink_device_entropy_pepper_secure", "eink_hardware_binding_entropy_pepper_change_in_production"}
INSECURE_ADMIN_PASSWORDS = {"", "admin123"}

class Settings(BaseSettings):
    PROJECT_NAME: str = "Pi'op"
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Storage Quotas
    DEFAULT_WORKSPACE_STORAGE_QUOTA_MB: int = 500

    # Typst compile wall-clock limit (seconds) for the worker subprocess
    TYPST_TIMEOUT_SECONDS: int = 15
    # Simultaneous typst worker subprocesses (each may use up to 2 GB)
    TYPST_MAX_CONCURRENT: int = 2

    # Device Fingerprinting Pepper
    FINGERPRINT_PEPPER: str = ""

    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR}/data/app.db"

    # Uploads directory
    UPLOAD_DIR: str = str(BASE_DIR / "data" / "uploads")

    # Superadmin defaults
    SUPERADMIN_USERNAME: str = "admin"
    SUPERADMIN_PASSWORD: str = ""

    # Allowed CORS origins (JSON list in env); empty disables CORS
    CORS_ORIGINS: list[str] = []

    class Config:
        env_file = ".env"
        extra = "ignore"

def ensure_secrets(s: Settings) -> None:
    path = Path(s.UPLOAD_DIR).parent / "secrets.json"
    stored = json.loads(path.read_text()) if path.exists() else {}
    values = {}
    generated = []
    for name in ("SECRET_KEY", "FINGERPRINT_PEPPER"):
        if getattr(s, name) not in INSECURE_SECRETS:
            continue
        if stored.get(name):
            value = stored[name]
        else:
            value = secrets.token_urlsafe(48)
            generated.append(name)
        setattr(s, name, value)
        values[name] = value
    if generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({**stored, **values}, f, indent=2)
        for name in generated:
            print(f"[Config] Generated {name} and stored it in {path}")

settings = Settings()
