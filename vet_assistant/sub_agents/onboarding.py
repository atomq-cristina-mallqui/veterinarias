"""OnboardingAgent: registro inicial de cliente y mascota para primer agendamiento."""
from __future__ import annotations

from google.adk.agents import LlmAgent

from vet_assistant import config
from vet_assistant.prompts._loader import load_prompt
from vet_assistant.tools.supabase_tools import (
    get_or_create_client,
    list_my_pets,
    register_pet,
    update_client_contact,
)

onboarding_agent = LlmAgent(
    name="onboarding_agent",
    model=config.ACTIVE_MODEL,
    description=(
        "Onboarding de primera vez para agendar: crea/actualiza cliente y registra "
        "mascota con flujo claro y corto. Usa el telefono del canal WhatsApp "
        "(wa_id) como telefono del cliente por defecto, sin pedirlo nuevamente."
    ),
    instruction=load_prompt("onboarding"),
    tools=[
        get_or_create_client,
        update_client_contact,
        list_my_pets,
        register_pet,
    ],
)
