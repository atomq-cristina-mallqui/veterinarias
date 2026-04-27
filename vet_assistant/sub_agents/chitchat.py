"""ChitChatAgent: maneja saludos, agradecimientos, despedidas y small talk."""
from __future__ import annotations

from google.adk.agents import LlmAgent

from vet_assistant import config
from vet_assistant.prompts._loader import load_prompt

chitchat_agent = LlmAgent(
    name="chitchat_agent",
    model=config.ACTIVE_MODEL,
    description=(
        "Maneja conversación amena: saludos, despedidas, agradecimientos, "
        "comentarios sobre la mascota, pequeñas charlas que no requieren acción. "
        "Úsame cuando el usuario solo está saludando, agradeciendo o haciendo "
        "small talk. NO me uses para preguntas con información concreta."
    ),
    instruction=load_prompt("chitchat"),
)
