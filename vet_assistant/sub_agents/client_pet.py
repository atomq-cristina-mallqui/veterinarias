"""ClientPetAgent: registra/actualiza cliente y mascotas."""
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

client_pet_agent = LlmAgent(
    name="client_pet_agent",
    model=config.ACTIVE_MODEL,
    description=(
        "Registra o actualiza al cliente y sus mascotas en la base de datos. "
        "Úsame cuando el usuario quiera registrarse, dar de alta una mascota, "
        "o cuando se necesiten esos datos antes de agendar una cita. "
        "Yo me encargo de pedir nombre, teléfono y datos de la mascota, "
        "calcular el tamaño automáticamente y persistir todo."
    ),
    instruction=load_prompt("client_pet"),
    tools=[
        get_or_create_client,
        update_client_contact,
        list_my_pets,
        register_pet,
    ],
)
