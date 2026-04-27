"""Cliente Supabase singleton.

Usa la service role key porque el agente actúa como backend confiable. En un despliegue
real con auth de usuarios habría que pasar a anon key + RLS.
"""
from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from vet_assistant import config


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    if not config.supabase_is_configured():
        raise RuntimeError(
            "Supabase no está configurado. Define SUPABASE_URL y "
            "SUPABASE_SERVICE_ROLE_KEY en el archivo .env."
        )
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
