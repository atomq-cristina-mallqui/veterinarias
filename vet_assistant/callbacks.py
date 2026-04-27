"""Callbacks de ciclo de vida del agente.

Se enchufan a `LlmAgent(before_agent_callback=..., after_agent_callback=...)`.

Usos actuales:
- `init_session_state`: al primer turno de cada invocación, asegura que el estado
  de la sesión tenga `user_id`, carga `client_id` si el cliente ya existe en Supabase
  y precarga el `user_summary` persistente para que el RootAgent pueda inyectarlo en
  su prompt y "recordar" al usuario entre sesiones.
"""
from __future__ import annotations

import logging
import secrets

from google.adk.agents.callback_context import CallbackContext

from vet_assistant import config
from vet_assistant.tools.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def _ensure_user_id(callback_context: CallbackContext) -> str:
    state = callback_context.state
    if state.get("user_id"):
        return str(state["user_id"])

    user_id = f"{config.ANON_USER_PREFIX}{secrets.token_hex(4)}"
    state["user_id"] = user_id
    state["is_anonymous"] = True
    logger.info("Sesión iniciada como usuario anónimo: %s", user_id)
    return user_id


def _preload_client_and_summary(state, user_id: str) -> None:
    if state.get("is_anonymous"):
        return

    if state.get("user_summary") is not None and state.get("client_id") is not None:
        return

    if not config.supabase_is_configured():
        return

    try:
        supabase = get_supabase()
    except Exception as e:
        logger.warning("Supabase no disponible al iniciar la sesión: %s", e)
        return

    try:
        if not state.get("client_id"):
            res = (
                supabase.table("clients")
                .select("id, full_name")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if res and res.data:
                state["client_id"] = res.data["id"]
                state["client_name"] = res.data.get("full_name")
    except Exception as e:
        logger.warning("Error cargando cliente: %s", e)

    try:
        if not state.get("user_summary"):
            res = (
                supabase.table("user_summaries")
                .select("summary")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if res and res.data and res.data.get("summary"):
                state["user_summary"] = res.data["summary"]
    except Exception as e:
        logger.warning("Error cargando user_summary: %s", e)


def init_session_state(callback_context: CallbackContext) -> None:
    """Inicializa user_id, client_id y user_summary en el state al primer turno."""
    state = callback_context.state
    user_id = _ensure_user_id(callback_context)
    _preload_client_and_summary(state, user_id)
