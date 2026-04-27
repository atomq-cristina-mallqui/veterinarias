"""PaymentAgent: gestiona pagos simulados de citas."""
from __future__ import annotations

from google.adk.agents import LlmAgent

from vet_assistant import config
from vet_assistant.prompts._loader import load_prompt
from vet_assistant.tools.supabase_tools import (
    get_payment_status,
    list_my_pending_payments,
    register_simulated_payment,
)

payment_agent = LlmAgent(
    name="payment_agent",
    model=config.ACTIVE_MODEL,
    description=(
        "Gestiona pagos simulados de citas: lista pendientes, consulta estado y "
        "registra el pago como 'paid'. Úsame cuando el usuario quiera pagar una "
        "cita, preguntar cuánto debe o consultar si su pago se registró."
    ),
    instruction=load_prompt("payment"),
    tools=[
        list_my_pending_payments,
        get_payment_status,
        register_simulated_payment,
    ],
)
