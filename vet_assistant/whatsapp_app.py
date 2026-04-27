"""Webhook de WhatsApp Cloud API para conectar Lucy por HTTP."""
from __future__ import annotations

import logging
import re
import inspect
import uuid
import asyncio
from typing import Any
from datetime import datetime, timedelta, timezone

import httpx
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.genai import types
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from vet_assistant.agent import root_agent
from vet_assistant import config

LOGGER = logging.getLogger("vet_assistant.whatsapp")

app = FastAPI(title="Vet Assistant WhatsApp Webhook")

_APP_NAME = "vet_assistant"
_SESSION_TIMEOUT = timedelta(hours=2)
_RESET_SESSION_COMMAND = "unsubscribe-session"
_DEDUP_TTL = timedelta(hours=24)
_processed_message_ids: dict[str, datetime] = {}
_user_locks: dict[str, asyncio.Lock] = {}


class WhatsAppWebhookPayload(BaseModel):
    object: str | None = None
    entry: list[dict[str, Any]] = []


def _extract_message(payload: dict[str, Any]) -> dict[str, str | None]:
    """Extrae metadatos relevantes del payload de WhatsApp."""
    try:
        entry = payload.get("entry", [])
        changes = entry[0].get("changes", [])
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return {
                "wa_id": None,
                "text": None,
                "message_id": None,
                "whatsapp_session_id": None,
            }
        message = messages[0]
        wa_id = message.get("from")
        message_id = message.get("id")
        # Algunas integraciones/proxies incluyen session_id en value/message.
        whatsapp_session_id = (
            value.get("session_id")
            or message.get("session_id")
            or (value.get("conversation") or {}).get("id")
        )
        if message.get("type") == "text":
            text = message.get("text", {}).get("body")
            return {
                "wa_id": wa_id,
                "text": text,
                "message_id": message_id,
                "whatsapp_session_id": whatsapp_session_id,
            }
        return {
            "wa_id": wa_id,
            "text": None,
            "message_id": message_id,
            "whatsapp_session_id": whatsapp_session_id,
        }
    except (KeyError, IndexError, AttributeError):
        return {
            "wa_id": None,
            "text": None,
            "message_id": None,
            "whatsapp_session_id": None,
        }


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


def _prune_processed_message_ids(now_utc: datetime) -> None:
    to_delete = [
        message_id
        for message_id, seen_at in _processed_message_ids.items()
        if now_utc - seen_at > _DEDUP_TTL
    ]
    for message_id in to_delete:
        _processed_message_ids.pop(message_id, None)


def _mark_message_seen(message_id: str | None) -> bool:
    """Devuelve True si es mensaje nuevo; False si ya fue procesado."""
    if not message_id:
        return True
    now_utc = datetime.now(timezone.utc)
    _prune_processed_message_ids(now_utc)
    if message_id in _processed_message_ids:
        return False
    _processed_message_ids[message_id] = now_utc
    return True


async def _resolve_session_id(
    wa_id: str,
    user_text: str,
    whatsapp_session_id: str | None,
) -> str:
    """Resuelve session_id según prioridad WhatsApp > comando reset > timeout."""
    if whatsapp_session_id:
        return whatsapp_session_id

    if user_text.strip().lower() == _RESET_SESSION_COMMAND:
        return f"wa-{wa_id}-{uuid.uuid4().hex[:10]}"

    sessions_resp = await _call_maybe_async(
        _session_service.list_sessions(app_name=_APP_NAME, user_id=wa_id)
    )
    sessions = list(getattr(sessions_resp, "sessions", []) or [])
    if not sessions:
        return f"wa-{wa_id}-{uuid.uuid4().hex[:10]}"

    latest = max(sessions, key=lambda s: float(getattr(s, "last_update_time", 0.0) or 0.0))
    last_update_epoch = float(getattr(latest, "last_update_time", 0.0) or 0.0)
    last_update = datetime.fromtimestamp(last_update_epoch, tz=timezone.utc)
    if datetime.now(timezone.utc) - last_update > _SESSION_TIMEOUT:
        return f"wa-{wa_id}-{uuid.uuid4().hex[:10]}"

    return str(latest.id)


async def _ensure_adk_session(wa_id: str, session_id: str) -> None:
    """Garantiza que exista la sesión ADK resuelta para el usuario."""
    session = await _call_maybe_async(
        _session_service.get_session(
            app_name=_APP_NAME,
            user_id=wa_id,
            session_id=session_id,
        )
    )
    if session:
        return
    await _call_maybe_async(
        _session_service.create_session(
            app_name=_APP_NAME,
            user_id=wa_id,
            session_id=session_id,
            state={
                "user_id": wa_id,
                "client_phone": wa_id,
                "channel": "whatsapp",
            },
        )
    )


async def _build_reply_text(wa_id: str, session_id: str, user_text: str) -> str:
    """Genera la respuesta vía root_agent (ADK) con sesiones persistentes."""
    await _ensure_adk_session(wa_id, session_id)
    message = types.Content(role="user", parts=[types.Part.from_text(text=user_text)])

    chunks: list[str] = []
    async for event in _runner.run_async(
        user_id=wa_id,
        session_id=session_id,
        new_message=message,
        state_delta={
            "user_id": wa_id,
            "client_phone": wa_id,
            "channel": "whatsapp",
        },
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


def _is_stale_session_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        isinstance(exc, ValueError)
        and "session has been modified in storage" in message
    )


def _get_user_lock(wa_id: str) -> asyncio.Lock:
    lock = _user_locks.get(wa_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[wa_id] = lock
    return lock


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


async def _process_incoming_message(
    wa_id: str,
    incoming_text: str,
    whatsapp_session_id: str | None,
) -> None:
    stage_start = datetime.now(timezone.utc)
    user_lock = _get_user_lock(wa_id)
    async with user_lock:
        if incoming_text.strip().lower() == _RESET_SESSION_COMMAND:
            fresh_session_id = await _resolve_session_id(
                wa_id=wa_id,
                user_text=incoming_text,
                whatsapp_session_id=whatsapp_session_id,
            )
            await _ensure_adk_session(wa_id, fresh_session_id)
            await _send_whatsapp_text(
                wa_id,
                "Listo, inicié una sesión nueva. ¿En qué te ayudo ahora?",
            )
            elapsed_ms = int((datetime.now(timezone.utc) - stage_start).total_seconds() * 1000)
            LOGGER.info("wa_metrics wa_id=%s stage=reset_session elapsed_ms=%d", wa_id, elapsed_ms)
            return

        resolve_start = datetime.now(timezone.utc)
        session_id = await _resolve_session_id(
            wa_id=wa_id,
            user_text=incoming_text,
            whatsapp_session_id=whatsapp_session_id,
        )
        resolve_ms = int((datetime.now(timezone.utc) - resolve_start).total_seconds() * 1000)
        try:
            runner_start = datetime.now(timezone.utc)
            reply_text = await _build_reply_text(wa_id, session_id, incoming_text)
            runner_ms = int((datetime.now(timezone.utc) - runner_start).total_seconds() * 1000)
        except Exception as e:
            if not _is_stale_session_error(e):
                raise
            LOGGER.warning(
                "Stale session detectada para wa_id=%s session_id=%s. Reintentando una vez.",
                wa_id,
                session_id,
            )
            await asyncio.sleep(0.15)
            retry_session_id = await _resolve_session_id(
                wa_id=wa_id,
                user_text=incoming_text,
                whatsapp_session_id=whatsapp_session_id,
            )
            runner_start = datetime.now(timezone.utc)
            reply_text = await _build_reply_text(wa_id, retry_session_id, incoming_text)
            runner_ms = int((datetime.now(timezone.utc) - runner_start).total_seconds() * 1000)
        send_start = datetime.now(timezone.utc)
        await _send_whatsapp_text(wa_id, reply_text)
        send_ms = int((datetime.now(timezone.utc) - send_start).total_seconds() * 1000)
        total_ms = int((datetime.now(timezone.utc) - stage_start).total_seconds() * 1000)
        LOGGER.info(
            "wa_metrics wa_id=%s session_id=%s resolve_ms=%d runner_ms=%d send_ms=%d total_ms=%d",
            wa_id,
            session_id,
            resolve_ms,
            runner_ms,
            send_ms,
            total_ms,
        )


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
async def receive_whatsapp_webhook(
    payload: WhatsAppWebhookPayload,
    background_tasks: BackgroundTasks,
) -> dict[str, bool]:
    """Recibe mensajes entrantes y responde con el agente."""
    body = payload.model_dump()
    extracted = _extract_message(body)
    wa_id = extracted["wa_id"]
    incoming_text = extracted["text"]
    message_id = extracted["message_id"]
    whatsapp_session_id = extracted["whatsapp_session_id"]

    if not wa_id or not incoming_text:
        return {"ok": True}

    if not _mark_message_seen(message_id):
        LOGGER.info("Duplicado detectado en WhatsApp, se omite respuesta. message_id=%s", message_id)
        return {"ok": True}

    # ACK rápido para evitar reintentos del webhook de Meta por timeout.
    background_tasks.add_task(
        _process_incoming_message,
        wa_id,
        incoming_text,
        whatsapp_session_id,
    )
    return {"ok": True}
