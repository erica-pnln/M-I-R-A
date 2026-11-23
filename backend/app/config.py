import os
from dotenv import load_dotenv

load_dotenv()

def _env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


GEMINI_API_KEY = _env_value("GEMINI_API_KEY", "GEMKEYINI_API_")
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
_RETIRED_GEMINI_MODELS = {
    "gemini-2.5-flash": DEFAULT_GEMINI_MODEL,
}


def _gemini_model(env_name: str, fallback: str) -> str:
    model = os.getenv(env_name, fallback).strip()
    return _RETIRED_GEMINI_MODELS.get(model, model)


GEMINI_MODEL = _gemini_model("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
GEMINI_ANALYSIS_API_KEY = os.getenv("GEMINI_ANALYSIS_API_KEY", "")
GEMINI_ANALYSIS_MODEL = _gemini_model("GEMINI_ANALYSIS_MODEL", GEMINI_MODEL)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
NEWS_REFRESH_TOKEN = os.getenv("NEWS_REFRESH_TOKEN", "")


def _cors_origins(value: str | None) -> list[str]:
    origins = [origin.strip() for origin in (value or "").split(",") if origin.strip()]
    if not origins:
        origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    if "http://localhost:3000" in origins:
        origins.append("http://localhost:3001")
    if "http://127.0.0.1:3000" in origins:
        origins.append("http://127.0.0.1:3001")
    return list(dict.fromkeys(origins))


CORS_ORIGINS = _cors_origins(os.getenv("CORS_ORIGINS"))
