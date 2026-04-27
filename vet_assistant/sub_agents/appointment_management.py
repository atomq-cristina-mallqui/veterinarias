"""AppointmentManagementAgent: ver, reprogramar y cancelar citas existentes."""
from __future__ import annotations

from google.adk.agents import LlmAgent

from vet_assistant import config
from vet_assistant.prompts._loader import load_prompt
from vet_assistant.tools.supabase_tools import (
    cancel_my_appointment,
    list_available_slots,
    list_my_appointments,
    reschedule_my_appointment,
)

appointment_management_agent = LlmAgent(
    name="appointment_management_agent",
    model=config.ACTIVE_MODEL,
    description=(
        "Gestiona citas EXISTENTES: lista las próximas, reprograma o cancela. "
        "Aplica la política flexible de hasta 2 horas antes. Úsame cuando el "
        "usuario quiera 'ver mis citas', 'cambiar mi cita', 'cancelar mi cita'. "
        "NO me uses para crear citas nuevas (eso le toca al scheduling_agent)."
    ),
    instruction=load_prompt("appointment_management"),
    tools=[
        list_my_appointments,
        list_available_slots,
        reschedule_my_appointment,
        cancel_my_appointment,
    ],
)
