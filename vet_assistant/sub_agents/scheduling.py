"""SchedulingAgent: agenda citas nuevas (consulta disponibilidad, crea la cita)."""
from __future__ import annotations

from google.adk.agents import LlmAgent

from vet_assistant import config
from vet_assistant.prompts._loader import load_prompt
from vet_assistant.tools.supabase_tools import (
    add_grooming_addon_to_appointment,
    create_appointment,
    create_multi_pet_same_time_appointments,
    get_user_booking_context,
    get_service_pricing_for_size,
    list_available_slots,
    list_my_appointments,
    list_my_pets,
    list_services,
)

scheduling_agent = LlmAgent(
    name="scheduling_agent",
    model=config.ACTIVE_MODEL,
    description=(
        "Agenda citas nuevas: consulta el catálogo de servicios, calcula "
        "disponibilidad por fecha + servicio + tamaño y crea la cita en estado "
        "'scheduled' con un registro de pago pendiente. Úsame cuando el usuario "
        "quiera reservar / agendar un servicio."
    ),
    instruction=load_prompt("scheduling"),
    tools=[
        list_services,
        get_user_booking_context,
        list_my_pets,
        list_my_appointments,
        get_service_pricing_for_size,
        list_available_slots,
        create_appointment,
        create_multi_pet_same_time_appointments,
        add_grooming_addon_to_appointment,
    ],
)
