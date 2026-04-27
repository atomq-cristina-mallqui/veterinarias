"""Webhook de WhatsApp Cloud API para conectar Lucy por HTTP."""
from __future__ import annotations

import logging
import re
import inspect
from typing import Any

import httpx
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.genai import types
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from vet_assistant.agent import root_agent
from vet_assistant import config

LOGGER = logging.getLogger("vet_assistant.whatsapp")

app = FastAPI(title="Vet Assistant WhatsApp Webhook")

_APP_NAME = "vet_assistant"


class WhatsAppWebhookPayload(BaseModel):
    object: str | None = None
    entry: list[dict[str, Any]] = []


def _extract_message(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extrae (wa_id, texto) del payload de WhatsApp."""
    try:
        entry = payload.get("entry", [])
        changes = entry[0].get("changes", [])
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None, None
        message = messages[0]
        wa_id = message.get("from")
        if message.get("type") == "text":
            text = message.get("text", {}).get("body")
            return wa_id, text
        return wa_id, None
    except (KeyError, IndexError, AttributeError):
        return None, None


def _normalize_db_url_for_adk(db_url: str) -> str:
    """ADK DatabaseSessionService usa SQLAlchemy async; preferimos driver psycopg."""
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return db_url


def _build_session_service():
    """Crea el servicio de sesión persistente (DB) con fallback en memoria."""
    if config.SUPABASE_DB_URL:
        try:
            db_url = _normalize_db_url_for_adk(config.SUPABASE_DB_URL)
            LOGGER.info("Usando DatabaseSessionService para sesiones ADK en Supabase.")
            return DatabaseSessionService(db_url=db_url)
        except Exception as e:
            LOGGER.warning(
                "No se pudo inicializar DatabaseSessionService (%s). "
                "Se usará InMemorySessionService temporalmente.",
                e,
            )
    else:
        LOGGER.warning(
            "SUPABASE_DB_URL no configurada. Se usará InMemorySessionService (no persistente)."
        )
    return InMemorySessionService()


_session_service = _build_session_service()
_runner = Runner(
    agent=root_agent,
    app_name=_APP_NAME,
    session_service=_session_service,
    auto_create_session=False,
)


def _format_for_whatsapp(text: str) -> str:
    """Convierte formato markdown a un formato amigable para WhatsApp."""
    cleaned = text.strip()
    if not cleaned:
        return "Gracias por escribir. ¿En qué puedo ayudarte hoy?"

    cleaned = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("**", "*")
    cleaned = cleaned.replace("`", "")
    cleaned = re.sub(r"(?<!\*)_(.+?)_(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


async def _call_maybe_async(result):
    if inspect.isawaitable(result):
        return await result
    return result


async def _ensure_adk_session(wa_id: str) -> None:
    """Garantiza que exista una sesión ADK para el wa_id actual."""
    session = await _call_maybe_async(
        _session_service.get_session(
            app_name=_APP_NAME,
            user_id=wa_id,
            session_id=wa_id,
        )
    )
    if session:
        return
    await _call_maybe_async(
        _session_service.create_session(
            app_name=_APP_NAME,
            user_id=wa_id,
            session_id=wa_id,
            state={
                "user_id": wa_id,
                "client_phone": wa_id,
                "channel": "whatsapp",
            },
        )
    )


async def _build_reply_text(wa_id: str, user_text: str) -> str:
    """Genera la respuesta vía root_agent (ADK) con sesiones persistentes."""
    await _ensure_adk_session(wa_id)
    message = types.Content(role="user", parts=[types.Part.from_text(text=user_text)])

    chunks: list[str] = []
    async for event in _runner.run_async(
        user_id=wa_id,
        session_id=wa_id,
        new_message=message,
    ):
        if not event.is_final_response():
            continue
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if getattr(part, "text", None):
                chunks.append(part.text)

    reply = "".join(chunks).strip()
    if not reply:
        reply = "Gracias por escribir. ¿En qué puedo ayudarte hoy?"
    return _format_for_whatsapp(reply)


async def _send_whatsapp_text(to_wa_id: str, text: str) -> None:
    """Envía un mensaje de texto por WhatsApp Cloud API."""
    if not config.WHATSAPP_ACCESS_TOKEN or not config.WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError(
            "Faltan WHATSAPP_ACCESS_TOKEN o WHATSAPP_PHONE_NUMBER_ID en variables de entorno."
        )

    url = (
        f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/"
        f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(url, json=body, headers=headers)
        if res.status_code >= 300:
            LOGGER.error("Error enviando WhatsApp: %s", res.text)
            raise HTTPException(status_code=502, detail="No se pudo enviar mensaje a WhatsApp")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/webhook/whatsapp", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> str:
    """Verificación del webhook exigida por Meta."""
    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="hub.mode invalido")
    if not config.WHATSAPP_VERIFY_TOKEN:
        raise HTTPException(status_code=500, detail="WHATSAPP_VERIFY_TOKEN no configurado")
    if hub_verify_token != config.WHATSAPP_VERIFY_TOKEN:
        raise HTTPException(status_code=403, detail="verify token invalido")
    return PlainTextResponse(content=hub_challenge, status_code=200)


@app.post("/webhook/whatsapp")
async def receive_whatsapp_webhook(payload: WhatsAppWebhookPayload) -> dict[str, bool]:
    """Recibe mensajes entrantes y responde con el agente."""
    body = payload.model_dump()
    wa_id, incoming_text = _extract_message(body)
    if not wa_id or not incoming_text:
        return {"ok": True}

    reply_text = await _build_reply_text(wa_id, incoming_text)
    await _send_whatsapp_text(wa_id, reply_text)
    return {"ok": True}
