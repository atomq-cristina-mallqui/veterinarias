"""FAQAgent: responde preguntas frecuentes con prompt hardcoded."""
from __future__ import annotations

from google.adk.agents import LlmAgent

from vet_assistant import config
from vet_assistant.prompts._loader import load_prompt

faq_agent = LlmAgent(
    name="faq_agent",
    model=config.ACTIVE_MODEL,
    description=(
        "Responde preguntas frecuentes sobre la clínica: horarios, ubicación, "
        "precios, servicios, políticas de cancelación, métodos de pago. "
        "Úsame cuando el usuario pregunte 'cuánto cuesta', 'a qué hora abren', "
        "'qué servicios ofrecen', 'cuál es la política de cancelación', etc."
    ),
    instruction=load_prompt("faq"),
)
