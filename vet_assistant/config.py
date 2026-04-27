"""Configuración central del asistente. Carga variables de entorno y expone constantes."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai").strip().lower()
GOOGLE_API_KEY: str | None = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

WHATSAPP_ACCESS_TOKEN: str | None = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID: str | None = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN: str | None = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_API_VERSION: str = os.getenv("WHATSAPP_API_VERSION", "v23.0")
WHATSAPP_SYSTEM_PROMPT: str = os.getenv(
    "WHATSAPP_SYSTEM_PROMPT",
    (
        "Eres Lucy, asistente de una clinica veterinaria. Responde siempre en "
        "espanol, de forma breve y amable, y enfocate en agendamiento, FAQ y "
        "atencion a clientes de la clinica."
    ),
)

DEMO_USER_ID: str = os.getenv("DEMO_USER_ID", "user_demo_1")
ANON_USER_PREFIX: str = os.getenv("ANON_USER_PREFIX", "anon_")
CLINIC_TIMEZONE: str = os.getenv("CLINIC_TIMEZONE", "America/Lima")
CLINIC_CURRENCY: str = os.getenv("CLINIC_CURRENCY", "PEN")

CLINIC_NAME: str = "Clínica Veterinaria Patitas Felices"
ASSISTANT_NAME: str = "Lucy"


def build_active_model() -> str:
    """Devuelve el modelo configurado para ADK.

    Importante: devolvemos SIEMPRE un string serializable para evitar errores de
    serialización en ADK Web/FastAPI al inspeccionar la configuración del agente.
    - `openai`: `openai/<model_name>`
    - `gemini` (fallback): identificador Gemini directo
    """
    if LLM_PROVIDER == "openai":
        return f"openai/{OPENAI_MODEL}"
    return GEMINI_MODEL


ACTIVE_MODEL: str = build_active_model()


def supabase_is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
