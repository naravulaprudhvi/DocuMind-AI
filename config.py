import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

# Suppress TensorFlow, oneDNN, and Windows symlink warnings globally
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

load_dotenv()  # reads the .env file


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    VECTOR_FOLDER = os.path.join(BASE_DIR, "vector_indexes")
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB upload limit

    # Database configuration (Cloud DATABASE_URL, SQLite fallback, or MySQL)
    DATABASE_URL = os.getenv("DATABASE_URL")
    USE_SQLITE = os.getenv("USE_SQLITE", "false").lower() in ("true", "1")

    if USE_SQLITE:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'documind.db')}"
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    elif DATABASE_URL:
        if DATABASE_URL.startswith("mysql://"):
            SQLALCHEMY_DATABASE_URI = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)
        elif DATABASE_URL.startswith("postgres://"):
            SQLALCHEMY_DATABASE_URI = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        else:
            SQLALCHEMY_DATABASE_URI = DATABASE_URL
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_recycle": 1800, "pool_pre_ping": True}
    else:
        DB_HOST = os.getenv("DB_HOST", "localhost")
        DB_PORT = os.getenv("DB_PORT", "3306")
        DB_USER = os.getenv("DB_USER", "root")
        DB_PASSWORD = os.getenv("DB_PASSWORD", "")
        DB_NAME = os.getenv("DB_NAME", "documind_db")

        # quote_plus makes passwords with @ # : etc. safe
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}"
            f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
        )
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        }

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Security and Session configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("true", "1")
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours

    # LLM and Local Model configuration
    # Options: "gemini", "ollama", "openai", "local_fallback"
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

    # Caching configuration
    ENABLE_QUERY_CACHE = os.getenv("ENABLE_QUERY_CACHE", "true").lower() in ("true", "1")
    QUERY_CACHE_TTL_SECONDS = int(os.getenv("QUERY_CACHE_TTL_SECONDS", "600"))

    # Ensure folders exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(VECTOR_FOLDER, exist_ok=True)
