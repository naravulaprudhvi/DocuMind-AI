import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

# Suppress TensorFlow, oneDNN, and Windows symlink warnings globally
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

load_dotenv()  # reads the .env file


def sanitize_database_url(url: str) -> str:
    """Auto-sanitizes database URLs, encoding special characters in passwords and adding SSL for Supabase/Neon."""
    if not url:
        return url
    url = url.strip().strip("'\"").strip()
    import re
    from urllib.parse import quote
    # Matches: postgresql://username:password@hostname:port/dbname
    m = re.match(r"^(?P<scheme>[a-zA-Z0-9\+\-]+://)(?P<user>[^:]+):(?P<password>.+)@(?P<host>[^@/]+)/(?P<rest>.*)$", url)
    if m:
        scheme = m.group("scheme")
        user = m.group("user")
        password = m.group("password")
        host = m.group("host")
        rest = m.group("rest")
        if "@" in password and "%40" not in password:
            encoded_password = quote(password, safe="")
            url = f"{scheme}{user}:{encoded_password}@{host}/{rest}"
    if ("supabase.co" in url or "neon.tech" in url or "pooler.supabase" in url) and "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    VECTOR_FOLDER = os.path.join(BASE_DIR, "vector_indexes")
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB upload limit

    # Database configuration (Cloud DATABASE_URL, SQLite fallback, or MySQL)
    # Check DATABASE_URL and common provider aliases
    DATABASE_URL = (
        os.getenv("DATABASE_URL")
        or os.getenv("SUPABASE_DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or os.getenv("POSTGRESQL_URL")
        or os.getenv("SUPABASE_DB_URL")
    )
    # Also check if user inadvertently pasted postgres connection into SUPABASE_URL
    if not DATABASE_URL and os.getenv("SUPABASE_URL", "").strip().startswith("postgres"):
        DATABASE_URL = os.getenv("SUPABASE_URL")

    if DATABASE_URL:
        DATABASE_URL = DATABASE_URL.strip().strip("'\"").strip()

    IS_CLOUD = bool(
        os.getenv("RENDER")
        or os.getenv("RENDER_SERVICE_ID")
        or os.getenv("RENDER_INSTANCE_ID")
        or os.getenv("VERCEL")
        or os.getenv("DYNO")
        or os.getenv("RAILWAY_STATIC_URL")
        or os.getenv("FLY_APP_NAME")
    )

    db_host = os.getenv("DB_HOST", "localhost").strip()
    is_localhost = db_host.lower() in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "")

    # On cloud platforms (Render, Railway, etc.), if no remote DATABASE_URL is set and DB_HOST is localhost,
    # we use SQLite because localhost has no MySQL server running inside the cloud container.
    USE_SQLITE = (
        os.getenv("USE_SQLITE", "false").lower() in ("true", "1")
        or (IS_CLOUD and not DATABASE_URL and is_localhost)
    )

    # 1. PRIMARY: External Cloud Database (Supabase, Neon, etc.) - ALWAYS takes precedence
    if DATABASE_URL:
        raw_url = sanitize_database_url(DATABASE_URL)
        if raw_url.startswith("postgres://"):
            SQLALCHEMY_DATABASE_URI = raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif raw_url.startswith("postgresql://") and "+psycopg2" not in raw_url:
            SQLALCHEMY_DATABASE_URI = raw_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        elif raw_url.startswith("mysql://") and "+pymysql" not in raw_url:
            SQLALCHEMY_DATABASE_URI = raw_url.replace("mysql://", "mysql+pymysql://", 1)
        else:
            SQLALCHEMY_DATABASE_URI = raw_url

        connect_args = {}
        if "postgres" in SQLALCHEMY_DATABASE_URI:
            connect_args = {
                "connect_timeout": 15,
                "application_name": "DocuMind-AI",
            }
        elif "mysql" in SQLALCHEMY_DATABASE_URI:
            connect_args = {"connect_timeout": 10}

        # Supabase / Neon Cloud PostgreSQL optimizations:
        # pool_recycle: 300 prevents dropped connections when serverless poolers idle
        # pool_pre_ping: True tests connection health before sending queries
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_recycle": 300,
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
    # 2. SECONDARY: Local or Cloud fallback SQLite
    elif USE_SQLITE:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'documind.db')}"
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "connect_args": {"timeout": 15},
        }
    else:
        DB_PORT = os.getenv("DB_PORT", "3306")
        DB_USER = os.getenv("DB_USER", "root")
        DB_PASSWORD = os.getenv("DB_PASSWORD", "")
        DB_NAME = os.getenv("DB_NAME", "documind_db")

        # quote_plus makes passwords with @ # : etc. safe
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}"
            f"@{db_host}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
        )
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_recycle": 1800,
            "pool_pre_ping": True,
            "connect_args": {"connect_timeout": 5},
        }

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Security and Session configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_CLOUD or os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("true", "1")
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days persistent session
    SESSION_PERMANENT = True

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

    @classmethod
    def get_db_telemetry(cls) -> dict:
        """Returns database persistence telemetry for live UI status indicators."""
        uri = getattr(cls, "SQLALCHEMY_DATABASE_URI", "")
        if "postgres" in uri:
            provider = "Supabase / Neon Cloud" if ("supabase" in uri or "neon" in uri or "pooler" in uri) else "Cloud PostgreSQL"
            return {
                "type": "Cloud PostgreSQL",
                "label": f"{provider} (Permanent)",
                "icon": "bi-database-fill-check",
                "badge_class": "bg-success-subtle text-success border-success-subtle",
                "is_persistent": True,
                "warning": None,
            }
        elif "mysql" in uri:
            is_local = "localhost" in uri or "127.0.0.1" in uri
            return {
                "type": "MySQL Database",
                "label": "Local MySQL" if is_local else "Cloud MySQL",
                "icon": "bi-database-check",
                "badge_class": "bg-info-subtle text-info border-info-subtle",
                "is_persistent": True,
                "warning": None,
            }
        else:
            if cls.IS_CLOUD:
                return {
                    "type": "Cloud Ephemeral SQLite",
                    "label": "Ephemeral Cloud (Temporary)",
                    "icon": "bi-database-exclamation",
                    "badge_class": "bg-warning-subtle text-warning-emphasis border-warning-subtle",
                    "is_persistent": False,
                    "warning": "Cloud ephemeral storage active! Add DATABASE_URL (Supabase/Neon) in environment variables so accounts and data are never erased on restart.",
                }
            return {
                "type": "Local SQLite",
                "label": "Local SQLite (Disk)",
                "icon": "bi-database-fill",
                "badge_class": "bg-secondary-subtle text-secondary border-secondary-subtle",
                "is_persistent": True,
                "warning": None,
            }
