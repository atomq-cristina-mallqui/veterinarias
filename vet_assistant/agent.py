"""Punto de entrada del asistente para ADK Web.

ADK detecta automáticamente la variable `root_agent` exportada por este módulo cuando
ejecutas `adk web` desde el directorio padre del paquete `vet_assistant/`.

Patrón coordinador: el RootAgent es el único que conversa con el usuario; invoca a los
sub-agentes especializados como herramientas (AgentTool) y reformula su salida en su
propia voz, manteniendo un único hilo conversacional.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.agent_tool import AgentTool

from vet_assistant import config
from vet_assistant.callbacks import init_session_state
from vet_assistant.prompts._loader import load_prompt
from vet_assistant.sub_agents.appointment_management import appointment_management_agent
from vet_assistant.sub_agents.chitchat import chitchat_agent
from vet_assistant.sub_agents.client_pet import client_pet_agent
from vet_assistant.sub_agents.faq import faq_agent
from vet_assistant.sub_agents.onboarding import onboarding_agent
from vet_assistant.sub_agents.payment import payment_agent
from vet_assistant.sub_agents.scheduling import scheduling_agent
from vet_assistant.tools.supabase_tools import get_my_summary, update_my_summary

_DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _format_today_clause(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz=tz)
    weekday = _DAYS_ES[now.isoweekday() - 1]
    month = _MONTHS_ES[now.month - 1]
    return (
        f"Hoy es **{weekday} {now.day} de {month} de {now.year}**, "
        f"hora actual: {now.strftime('%H:%M')} ({tz_name})."
    )


def _root_instruction(ctx: ReadonlyContext) -> str:
    """Inyecta dinámicamente al prompt: fecha actual, datos del cliente y memoria."""
    base = load_prompt("root")
    state = ctx.state

    runtime: list[str] = []

    runtime.append("## Contexto de tiempo (no inventes la fecha)")
    runtime.append(_format_today_clause(config.CLINIC_TIMEZONE))
    runtime.append(
        "Cuando el usuario diga expresiones relativas (mañana, el viernes, la próxima "
        "semana, en 3 días), conviértelas a fecha exacta en formato YYYY-MM-DD usando "
        "la fecha de arriba. Recuerda que la clínica solo atiende lunes a viernes."
    )

    sections = []
    client_name = state.get("client_name")
    user_summary = state.get("user_summary")
    if client_name:
        sections.append(f"- **Cliente actual**: {client_name}")
    if user_summary:
        sections.append(f"- **Memoria persistente**:\n  {user_summary}")

    if sections:
        runtime.append("## Contexto del usuario actual")
        runtime.extend(sections)
        runtime.append(
            "Usa esta memoria para personalizar el saludo y el flujo (ej. saludar por "
            "nombre, mencionar mascotas conocidas). NO la cites textualmente al "
            "usuario; úsala como contexto interno."
        )

    return base + "\n\n" + "\n\n".join(runtime)


root_agent = LlmAgent(
    name="lucy_root",
    model=config.ACTIVE_MODEL,
    description=(
        "Asistente conversacional de la Clínica Veterinaria Patitas Felices. "
        "Coordina saludo, FAQs, onboarding de primera vez, registro de "
        "cliente/mascota, agendamiento, "
        "reprogramación, cancelación y pagos."
    ),
    instruction=_root_instruction,
    before_agent_callback=init_session_state,
    tools=[
        AgentTool(agent=faq_agent),
        AgentTool(agent=chitchat_agent),
        AgentTool(agent=onboarding_agent),
        AgentTool(agent=client_pet_agent),
        AgentTool(agent=scheduling_agent),
        AgentTool(agent=appointment_management_agent),
        AgentTool(agent=payment_agent),
        get_my_summary,
        update_my_summary,
    ],
)
