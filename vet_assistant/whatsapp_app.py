"""Webhook de WhatsApp Cloud API para conectar Lucy por HTTP."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from openai import OpenAI
from pydantic import BaseModel

from vet_assistant import config

LOGGER = logging.getLogger("vet_assistant.whatsapp")

app = FastAPI(title="Vet Assistant WhatsApp Webhook")

_openai_client: OpenAI | None = None


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


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY no configurada. Define OPENAI_API_KEY para responder por WhatsApp."
            )
        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


def _build_reply_text(user_text: str) -> str:
    """Genera la respuesta del agente usando OpenAI."""
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": config.WHATSAPP_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.4,
    )
    text = response.choices[0].message.content or ""
    return text.strip() or "Gracias por escribir. ¿En qué puedo ayudarte hoy?"


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

    reply_text = _build_reply_text(incoming_text)
    await _send_whatsapp_text(wa_id, reply_text)
    return {"ok": True}
