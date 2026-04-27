"""Herramientas (tools) que los sub-agentes exponen a través de ADK.

Convenciones:
- Todas las funciones devuelven dicts/listas JSON-serializables.
- Cuando hay error de validación (cliente inexistente, fuera de horario, etc.) se
  devuelve `{"ok": false, "error": "...", "code": "..."}` para que el LLM pueda
  explicárselo al usuario sin lanzar excepción.
- Todas las funciones reciben `tool_context: ToolContext` como último parámetro para
  poder leer/escribir en el estado de la sesión (persistir client_id, etc.).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from google.adk.tools import ToolContext

from vet_assistant import config
from vet_assistant.tools.availability import (
    has_overlap,
    list_available_slots_impl,
    resolve_service,
)
from vet_assistant.tools.pet_size_rules import derive_pet_size
from vet_assistant.tools.supabase_client import get_supabase

# =============================================================================
# Helpers internos
# =============================================================================


def _ok(data: Any = None, **extra: Any) -> dict:
    out: dict = {"ok": True}
    if data is not None:
        out["data"] = data
    out.update(extra)
    return out


def _err(code: str, message: str, **extra: Any) -> dict:
    out = {"ok": False, "code": code, "error": message}
    out.update(extra)
    return out


def _resolve_user_id(tool_context: ToolContext) -> str:
    """Obtiene el user_id de la sesión.

    Prioridad:
      1. `state['user_id']` (puesto por el callback de inicio de sesión).
      2. Usuario anónimo por sesión cuando no hay user_id explícito.
    """
    state = tool_context.state
    if "user_id" in state and state["user_id"]:
        return str(state["user_id"])
    anon_user_id = f"{config.ANON_USER_PREFIX}{secrets.token_hex(4)}"
    state["user_id"] = anon_user_id
    state["is_anonymous"] = True
    return anon_user_id


# =============================================================================
# Cliente y mascota (Fase 3)
# =============================================================================


def get_or_create_client(
    full_name: str,
    phone: Optional[str],
    email: Optional[str],
    tool_context: ToolContext,
) -> dict:
    """Busca al cliente actual por user_id; si no existe, lo crea con los datos dados.

    Args:
        full_name: nombre completo del cliente (requerido para crearlo si no existe).
        phone: teléfono (opcional, recomendado).
        email: email (opcional).

    Devuelve `{ok, data: {id, user_id, full_name, phone, email, was_created}}`.
    """
    supabase = get_supabase()
    user_id = _resolve_user_id(tool_context)

    existing = (
        supabase.table("clients")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if existing and existing.data:
        client = existing.data
        client["was_created"] = False
        tool_context.state["client_id"] = client["id"]
        tool_context.state["client_verified"] = True
        return _ok(client)

    if not full_name or not full_name.strip():
        return _err(
            "missing_name",
            "Para registrarte como cliente necesito tu nombre completo. ¿Me lo confirmas?",
        )

    payload = {
        "user_id": user_id,
        "full_name": full_name.strip(),
        "phone": phone.strip() if phone else None,
        "email": email.strip() if email else None,
    }
    inserted = supabase.table("clients").insert(payload).execute()
    client = inserted.data[0]
    client["was_created"] = True
    tool_context.state["client_id"] = client["id"]
    tool_context.state["client_verified"] = True
    return _ok(client)


def update_client_contact(
    phone: Optional[str],
    email: Optional[str],
    tool_context: ToolContext,
) -> dict:
    """Actualiza teléfono/email del cliente actual. Pasa None en los campos a no tocar."""
    supabase = get_supabase()
    user_id = _resolve_user_id(tool_context)

    updates: dict = {}
    if phone is not None:
        updates["phone"] = phone.strip() or None
    if email is not None:
        updates["email"] = email.strip() or None
    if not updates:
        return _err("no_changes", "No hay cambios para aplicar.")

    res = (
        supabase.table("clients")
        .update(updates)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        return _err("client_not_found", "No encontré tu registro de cliente.")
    return _ok(res.data[0])


def list_my_pets(tool_context: ToolContext) -> dict:
    """Lista las mascotas del cliente actual.

    Devuelve `{ok, data: [pets...]}`. Si el cliente aún no existe, devuelve lista vacía.
    """
    supabase = get_supabase()
    user_id = _resolve_user_id(tool_context)

    client_res = (
        supabase.table("clients")
        .select("id")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not (client_res and client_res.data):
        return _ok([], note="client_not_registered")

    client_id = client_res.data["id"]
    tool_context.state["client_id"] = client_id
    tool_context.state["client_verified"] = True

    pets_res = (
        supabase.table("pets")
        .select("id, name, species, breed, weight_kg, size, birth_date, notes")
        .eq("client_id", client_id)
        .order("name")
        .execute()
    )
    return _ok(pets_res.data or [])


def register_pet(
    name: str,
    species: str,
    breed: Optional[str],
    weight_kg: Optional[float],
    birth_date: Optional[str],
    notes: Optional[str],
    tool_context: ToolContext,
) -> dict:
    """Registra una mascota nueva para el cliente actual.

    Args:
        name: nombre de la mascota.
        species: 'dog', 'cat' u 'other'.
        breed: raza (opcional).
        weight_kg: peso en kg (requerido para perro y otros; opcional para gato).
        birth_date: fecha de nacimiento ISO 'YYYY-MM-DD' (opcional).
        notes: notas adicionales (opcional).

    El tamaño (`small`/`medium`/`large`) se calcula automáticamente para perro y gato.
    """
    species_norm = (species or "").strip().lower()
    if species_norm not in ("dog", "cat", "other"):
        return _err(
            "invalid_species",
            "La especie debe ser 'dog' (perro), 'cat' (gato) u 'other' (otra).",
        )

    if not name or not name.strip():
        return _err("missing_name", "Necesito el nombre de la mascota.")

    if species_norm == "dog" and weight_kg is None:
        return _err(
            "missing_weight",
            "Para un perro necesito el peso aproximado en kg para definir el tamaño.",
        )

    derived_size = derive_pet_size(species_norm, weight_kg)
    if species_norm == "other" and derived_size is None:
        # Para 'other' aceptamos sin tamaño; quedará null y el agente confirmará al agendar.
        pass

    supabase = get_supabase()
    user_id = _resolve_user_id(tool_context)
    client_res = (
        supabase.table("clients")
        .select("id")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not (client_res and client_res.data):
        return _err(
            "client_not_registered",
            "Antes de registrar tu mascota necesito tus datos de cliente "
            "(nombre completo y teléfono).",
        )

    client_id = client_res.data["id"]
    tool_context.state["client_id"] = client_id
    tool_context.state["client_verified"] = True

    payload = {
        "client_id": client_id,
        "name": name.strip(),
        "species": species_norm,
        "breed": breed.strip() if breed else None,
        "weight_kg": float(weight_kg) if weight_kg is not None else None,
        "size": derived_size,
        "birth_date": birth_date,
        "notes": notes.strip() if notes else None,
    }
    inserted = supabase.table("pets").insert(payload).execute()
    pet = inserted.data[0]
    tool_context.state["selected_pet_id"] = pet["id"]
    tool_context.state["selected_pet_name"] = pet.get("name")
    return _ok(pet)


# =============================================================================
# Servicios y agenda (Fase 4)
# =============================================================================


def list_services(tool_context: ToolContext) -> dict:
    """Lista los servicios activos de la clínica con su tipo de sala y precios.

    Para servicios con tarifa por tamaño (baño, peluquería) se devuelven los precios
    por tamaño en `prices_by_size`.
    """
    supabase = get_supabase()
    svc_res = (
        supabase.table("services")
        .select("id, code, name, description, room_type, duration_default_min, "
                "price_default, requires_pet_size, is_active")
        .eq("is_active", True)
        .order("name")
        .execute()
    )
    services = svc_res.data or []

    grooming_ids = [s["id"] for s in services if s["requires_pet_size"]]
    durations_by_service: dict[str, list[dict]] = {}
    if grooming_ids:
        d_res = (
            supabase.table("service_durations")
            .select("service_id, pet_size, duration_min, price")
            .in_("service_id", grooming_ids)
            .execute()
        )
        for row in d_res.data or []:
            durations_by_service.setdefault(row["service_id"], []).append(row)

    out = []
    for s in services:
        item = {
            "code": s["code"],
            "name": s["name"],
            "description": s["description"],
            "room_type": s["room_type"],
            "requires_pet_size": s["requires_pet_size"],
        }
        if s["requires_pet_size"]:
            item["prices_by_size"] = sorted(
                [
                    {
                        "pet_size": d["pet_size"],
                        "duration_min": d["duration_min"],
                        "price": float(d["price"]),
                    }
                    for d in durations_by_service.get(s["id"], [])
                ],
                key=lambda x: {"small": 0, "medium": 1, "large": 2}[x["pet_size"]],
            )
        else:
            item["duration_min"] = s["duration_default_min"]
            item["price"] = float(s["price_default"]) if s["price_default"] else None
        out.append(item)

    return _ok(out)


def get_service_pricing_for_size(
    service_code: str,
    pet_size: Optional[str],
    tool_context: ToolContext,
) -> dict:
    """Devuelve duración y precio aplicables para un servicio + tamaño dado.

    `pet_size` puede omitirse (None) si el servicio no lo requiere (consulta o
    vacunación).
    """
    try:
        svc = resolve_service(service_code, pet_size)
    except ValueError as e:
        return _err("service_resolution", str(e))

    return _ok(
        {
            "code": svc.code,
            "name": svc.name,
            "room_type": svc.room_type,
            "duration_min": svc.duration_min,
            "price": svc.price,
        }
    )


def list_available_slots(
    target_date: str,
    service_code: str,
    pet_size: Optional[str],
    tool_context: ToolContext,
    max_slots: int = 64,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
) -> dict:
    """Lista los slots disponibles para una fecha + servicio + tamaño.

    Args:
        target_date: 'YYYY-MM-DD' (zona horaria America/Lima).
        service_code: 'consulta_general', 'vacunacion', 'bano' o 'peluqueria'.
        pet_size: 'small'/'medium'/'large'. Solo requerido para baño y peluquería.
        max_slots: cuántos slots devolver (default 64).
        from_time: 'HH:MM' local. Si se pasa, solo se devuelven slots cuyo inicio sea
            >= este valor. Aplica antes del recorte por `max_slots`.
        to_time: 'HH:MM' local. Si se pasa, solo se devuelven slots cuyo inicio sea
            < este valor. Aplica antes del recorte por `max_slots`.

    Devuelve: `{ok, service, date, slots: [{start_time, end_time, room_id, room_name}]}`.
    Los `start_time`/`end_time` vienen en ISO 8601 con timezone.
    """
    out = list_available_slots_impl(
        target_date=target_date,
        service_code=service_code,
        pet_size=pet_size,
        max_slots=max_slots,
        from_time=from_time,
        to_time=to_time,
    )
    if out.get("ok") and out.get("slots"):
        first = out["slots"][0]
        tool_context.state["last_quoted_slot"] = first
        tool_context.state["last_quoted_service"] = out["service"]
    return out


def _resolve_client_id(tool_context: ToolContext) -> Optional[str]:
    state = tool_context.state
    if state.get("client_id"):
        return state["client_id"]
    user_id = _resolve_user_id(tool_context)
    res = (
        get_supabase()
        .table("clients")
        .select("id")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if res and res.data:
        state["client_id"] = res.data["id"]
        return res.data["id"]
    return None


def create_appointment(
    pet_id: str,
    service_code: str,
    start_time: str,
    tool_context: ToolContext,
    notes: Optional[str] = None,
) -> dict:
    """Crea una cita para la mascota indicada.

    Args:
        pet_id: UUID de la mascota (debe pertenecer al cliente actual).
        service_code: código del servicio.
        start_time: ISO 8601 con timezone, p.ej. '2026-05-04T10:00:00-05:00'.
        notes: nota opcional.

    Internamente:
      - resuelve duración + precio según el tamaño actual de la mascota,
      - elige el primer room libre del room_type del servicio en ese horario,
      - crea la cita en estado 'scheduled' y un registro de pago en 'pending'.
    """
    supabase = get_supabase()
    client_id = _resolve_client_id(tool_context)
    if not client_id:
        return _err(
            "client_not_registered",
            "Necesito tener tus datos de cliente registrados antes de crear la cita.",
        )

    pet_res = (
        supabase.table("pets")
        .select("id, client_id, name, species, size")
        .eq("id", pet_id)
        .maybe_single()
        .execute()
    )
    if not (pet_res and pet_res.data):
        return _err("pet_not_found", "No encontré la mascota indicada.")
    pet = pet_res.data
    if pet["client_id"] != client_id:
        return _err("pet_not_yours", "Esa mascota no pertenece a tu cuenta.")

    # Política clínica: consulta general y vacunación solo para perros y gatos.
    pet_species = (pet.get("species") or "").strip().lower()
    if service_code in {"consulta_general", "vacunacion"} and pet_species not in {"dog", "cat"}:
        return _err(
            "species_not_supported_for_medical",
            "Por ahora, consulta médica y vacunación solo están disponibles para perros y gatos.",
        )

    try:
        svc = resolve_service(service_code, pet.get("size"))
    except ValueError as e:
        return _err("service_resolution", str(e))

    try:
        start_dt = datetime.fromisoformat(start_time)
    except ValueError:
        return _err("invalid_start_time", f"Formato de hora inválido: '{start_time}'.")
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=ZoneInfo("America/Lima"))

    settings = (
        supabase.table("clinic_settings").select("*").eq("id", 1).single().execute().data
    )
    tz = ZoneInfo(settings.get("timezone") or "America/Lima")
    start_local = start_dt.astimezone(tz)

    if start_local.isoweekday() not in (settings.get("operating_days") or [1, 2, 3, 4, 5]):
        return _err("non_operating_day", "Ese día la clínica no atiende.")

    end_local = start_local + timedelta(minutes=svc.duration_min)
    op = str(settings["opening_time"])
    cl = str(settings["closing_time"])
    op_h, op_m = (int(x) for x in op.split(":")[:2])
    cl_h, cl_m = (int(x) for x in cl.split(":")[:2])
    day_start = start_local.replace(hour=op_h, minute=op_m, second=0, microsecond=0)
    day_end = start_local.replace(hour=cl_h, minute=cl_m, second=0, microsecond=0)
    if start_local < day_start or end_local > day_end:
        return _err(
            "outside_hours",
            f"La cita debe iniciar y terminar dentro del horario {op}-{cl}.",
        )

    if start_local <= datetime.now(tz=tz):
        return _err("in_the_past", "Esa hora ya pasó. Elige un horario futuro.")

    rooms = (
        supabase.table("rooms")
        .select("id, name")
        .eq("room_type", svc.room_type)
        .eq("is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )
    chosen_room = None
    for room in rooms:
        if not has_overlap(room["id"], start_local, end_local):
            chosen_room = room
            break
    if not chosen_room:
        return _err(
            "no_room_available",
            "No hay sala libre en ese horario. ¿Te muestro otros slots?",
        )

    payload = {
        "client_id": client_id,
        "pet_id": pet_id,
        "service_id": svc.id,
        "room_id": chosen_room["id"],
        "start_time": start_local.isoformat(),
        "end_time": end_local.isoformat(),
        "status": "scheduled",
        "total_amount": svc.price,
        "notes": notes,
    }
    try:
        inserted = supabase.table("appointments").insert(payload).execute()
    except Exception as e:
        return _err("insert_failed", f"No se pudo crear la cita: {e}")

    appt = inserted.data[0]
    supabase.table("payments").insert(
        {
            "appointment_id": appt["id"],
            "amount": svc.price,
            "status": "pending",
            "method": "simulated",
        }
    ).execute()

    tool_context.state["last_appointment_id"] = appt["id"]
    tool_context.state["selected_pet_id"] = pet_id
    return _ok(
        {
            "appointment_id": appt["id"],
            "pet_name": pet["name"],
            "service": svc.name,
            "room": chosen_room["name"],
            "start_time": start_local.isoformat(),
            "end_time": end_local.isoformat(),
            "duration_min": svc.duration_min,
            "amount": svc.price,
            "currency": settings.get("currency") or "PEN",
            "payment_status": "pending",
        }
    )


def add_grooming_addon_to_appointment(
    appointment_id: str,
    addon_service_code: str,
    tool_context: ToolContext,
    prefer_immediate: bool = True,
) -> dict:
    """Agrega un adicional de grooming como segunda cita ligada a una cita base.

    Crea una nueva cita para el mismo cliente/mascota, idealmente justo después de la
    cita base (mismo día). Si no hay hueco contiguo, toma el siguiente slot disponible.
    """
    supabase = get_supabase()
    client_id = _resolve_client_id(tool_context)
    if not client_id:
        return _err("client_not_registered", "No tienes registro de cliente.")

    base_res = (
        supabase.table("appointments")
        .select(
            "id, client_id, pet_id, start_time, end_time, status, "
            "pets(id, name, size), services(code, name, room_type)"
        )
        .eq("id", appointment_id)
        .maybe_single()
        .execute()
    )
    if not (base_res and base_res.data):
        return _err("appointment_not_found", "No encontré la cita base para agregar el adicional.")
    base = base_res.data
    if base["client_id"] != client_id:
        return _err("not_your_appointment", "Esa cita no pertenece a tu cuenta.")
    if base["status"] != "scheduled":
        return _err("not_modifiable", "Solo se pueden agregar adicionales a citas en estado 'scheduled'.")

    base_service = base.get("services") or {}
    if base_service.get("room_type") != "grooming":
        return _err(
            "invalid_base_service",
            "Los adicionales de grooming solo se pueden agregar a citas de baño o peluquería.",
        )

    if addon_service_code not in {"GROOM_PAW_TRIM", "GROOM_DESHED", "GROOM_MASK"}:
        return _err(
            "invalid_addon",
            "El adicional debe ser GROOM_PAW_TRIM, GROOM_DESHED o GROOM_MASK.",
        )

    try:
        addon_svc = resolve_service(addon_service_code, None)
    except ValueError as e:
        return _err("service_resolution", str(e))

    if addon_svc.room_type != "grooming":
        return _err("invalid_addon", "El servicio indicado no es un adicional de grooming válido.")

    settings = (
        supabase.table("clinic_settings").select("*").eq("id", 1).single().execute().data
    )
    tz = ZoneInfo(settings.get("timezone") or "America/Lima")
    base_start = datetime.fromisoformat(base["start_time"]).astimezone(tz)
    base_end = datetime.fromisoformat(base["end_time"]).astimezone(tz)
    target_date = base_start.date().isoformat()

    slots_out = list_available_slots_impl(
        target_date=target_date,
        service_code=addon_service_code,
        pet_size=None,
        max_slots=50,
    )
    if not slots_out.get("ok"):
        return _err(
            slots_out.get("code", "addon_slots_error"),
            slots_out.get("error", "No pude calcular horarios para el adicional."),
        )

    slots = slots_out.get("slots") or []
    if prefer_immediate:
        filtered = [
            s
            for s in slots
            if datetime.fromisoformat(s["start_time"]).astimezone(tz) >= base_end
        ]
        if filtered:
            slots = filtered

    if not slots:
        return _err(
            "no_addon_slot_available",
            "No encontré horario disponible para ese adicional el mismo día.",
        )

    chosen = slots[0]
    start_local = datetime.fromisoformat(chosen["start_time"]).astimezone(tz)
    end_local = datetime.fromisoformat(chosen["end_time"]).astimezone(tz)

    payload = {
        "client_id": client_id,
        "pet_id": base["pet_id"],
        "service_id": addon_svc.id,
        "room_id": chosen["room_id"],
        "start_time": start_local.isoformat(),
        "end_time": end_local.isoformat(),
        "status": "scheduled",
        "total_amount": addon_svc.price,
        "notes": f"Adicional de {base_service.get('name') or 'grooming'} (cita base {appointment_id}).",
    }
    inserted = supabase.table("appointments").insert(payload).execute()
    addon_appt = inserted.data[0]
    supabase.table("payments").insert(
        {
            "appointment_id": addon_appt["id"],
            "amount": addon_svc.price,
            "status": "pending",
            "method": "simulated",
        }
    ).execute()

    tool_context.state["last_appointment_id"] = addon_appt["id"]
    tool_context.state["selected_pet_id"] = base["pet_id"]
    tool_context.state["selected_pet_name"] = (base.get("pets") or {}).get("name")

    return _ok(
        {
            "base_appointment_id": appointment_id,
            "addon_appointment_id": addon_appt["id"],
            "pet_name": (base.get("pets") or {}).get("name"),
            "addon_service": addon_svc.name,
            "room": chosen["room_name"],
            "start_time": start_local.isoformat(),
            "end_time": end_local.isoformat(),
            "duration_min": addon_svc.duration_min,
            "amount": addon_svc.price,
            "currency": settings.get("currency") or "PEN",
            "payment_status": "pending",
        }
    )


# =============================================================================
# Gestión de citas existentes (Fase 5)
# =============================================================================


def _appointment_with_relations(row: dict) -> dict:
    """Aplana un row con joins de pet/service/room a un dict legible."""
    pet = row.get("pets") or {}
    svc = row.get("services") or {}
    room = row.get("rooms") or {}
    payment = row.get("payments") or {}
    if isinstance(payment, list):
        payment = payment[0] if payment else {}
    return {
        "appointment_id": row["id"],
        "status": row["status"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "total_amount": float(row["total_amount"]) if row.get("total_amount") else None,
        "notes": row.get("notes"),
        "pet": {"id": pet.get("id"), "name": pet.get("name"), "species": pet.get("species")},
        "service": {"code": svc.get("code"), "name": svc.get("name")},
        "room": {"id": room.get("id"), "name": room.get("name")},
        "payment": {
            "status": payment.get("status"),
            "amount": float(payment["amount"]) if payment.get("amount") else None,
            "paid_at": payment.get("paid_at"),
        }
        if payment
        else None,
    }


def list_my_appointments(
    tool_context: ToolContext,
    only_upcoming: bool = True,
    include_canceled: bool = False,
    limit: int = 20,
) -> dict:
    """Lista las citas del cliente actual.

    Args:
        only_upcoming: si True, solo citas con start_time >= ahora.
        include_canceled: si False, omite las canceladas.
        limit: máximo de resultados.
    """
    supabase = get_supabase()
    client_id = _resolve_client_id(tool_context)
    if not client_id:
        return _ok([], note="client_not_registered")

    settings = (
        supabase.table("clinic_settings").select("timezone").eq("id", 1).single().execute().data
    )
    tz = ZoneInfo(settings.get("timezone") or "America/Lima")
    now_iso = datetime.now(tz=tz).isoformat()

    q = (
        supabase.table("appointments")
        .select(
            "id, start_time, end_time, status, total_amount, notes, "
            "pets(id, name, species), services(code, name), rooms(id, name), "
            "payments(status, amount, paid_at)"
        )
        .eq("client_id", client_id)
        .order("start_time")
        .limit(limit)
    )
    if only_upcoming:
        q = q.gte("start_time", now_iso)
    if not include_canceled:
        q = q.neq("status", "canceled")

    res = q.execute()
    items = [_appointment_with_relations(r) for r in (res.data or [])]
    return _ok(items)


def _within_window_hours(start_iso: str, hours: int, tz: ZoneInfo) -> tuple[bool, float]:
    """Devuelve (cumple_ventana, horas_restantes_hasta_la_cita)."""
    start_dt = datetime.fromisoformat(start_iso).astimezone(tz)
    delta = start_dt - datetime.now(tz=tz)
    remaining = delta.total_seconds() / 3600.0
    return remaining >= hours, remaining


def cancel_my_appointment(appointment_id: str, tool_context: ToolContext) -> dict:
    """Cancela una cita propia, validando la ventana de 2 horas.

    Si la cita ya fue pagada, marca el pago como `refunded` (simulado).
    """
    supabase = get_supabase()
    client_id = _resolve_client_id(tool_context)
    if not client_id:
        return _err("client_not_registered", "No tienes registro de cliente.")

    res = (
        supabase.table("appointments")
        .select("id, client_id, start_time, status")
        .eq("id", appointment_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        return _err("appointment_not_found", "No encontré esa cita.")
    appt = res.data
    if appt["client_id"] != client_id:
        return _err("not_your_appointment", "Esa cita no es tuya.")
    if appt["status"] in ("canceled", "completed", "no_show"):
        return _err(
            "already_finalized",
            f"Esa cita ya está en estado '{appt['status']}'; no se puede cancelar.",
        )

    settings = (
        supabase.table("clinic_settings")
        .select("timezone, cancellation_window_hours")
        .eq("id", 1)
        .single()
        .execute()
        .data
    )
    tz = ZoneInfo(settings.get("timezone") or "America/Lima")
    window = int(settings.get("cancellation_window_hours") or 2)
    in_window, remaining = _within_window_hours(appt["start_time"], window, tz)
    if not in_window:
        return _err(
            "window_exceeded",
            f"La ventana para cancelar es de {window}h antes (faltan {remaining:.1f}h). "
            f"Por favor llama a la clínica.",
        )

    supabase.table("appointments").update({"status": "canceled"}).eq(
        "id", appointment_id
    ).execute()

    payment = (
        supabase.table("payments")
        .select("id, status")
        .eq("appointment_id", appointment_id)
        .maybe_single()
        .execute()
    )
    refunded = False
    if payment and payment.data and payment.data["status"] == "paid":
        supabase.table("payments").update({"status": "refunded"}).eq(
            "id", payment.data["id"]
        ).execute()
        refunded = True

    return _ok(
        {"appointment_id": appointment_id, "status": "canceled", "refunded": refunded}
    )


def reschedule_my_appointment(
    appointment_id: str,
    new_start_time: str,
    tool_context: ToolContext,
) -> dict:
    """Reprograma una cita propia a un nuevo horario.

    Valida la ventana de 2h, el horario operativo y la disponibilidad de sala. Reusa la
    misma sala si está libre; si no, elige la primera libre del mismo room_type.
    """
    supabase = get_supabase()
    client_id = _resolve_client_id(tool_context)
    if not client_id:
        return _err("client_not_registered", "No tienes registro de cliente.")

    settings = (
        supabase.table("clinic_settings").select("*").eq("id", 1).single().execute().data
    )
    tz = ZoneInfo(settings.get("timezone") or "America/Lima")

    res = (
        supabase.table("appointments")
        .select(
            "id, client_id, room_id, status, start_time, end_time, "
            "services(id, code, room_type, requires_pet_size, duration_default_min, price_default), "
            "pets(id, size)"
        )
        .eq("id", appointment_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        return _err("appointment_not_found", "No encontré esa cita.")
    appt = res.data
    if appt["client_id"] != client_id:
        return _err("not_your_appointment", "Esa cita no es tuya.")
    if appt["status"] != "scheduled":
        return _err(
            "not_reschedulable",
            f"Solo citas en estado 'scheduled' se pueden reprogramar (actual: '{appt['status']}').",
        )

    window = int(settings.get("reschedule_window_hours") or 2)
    in_window, remaining = _within_window_hours(appt["start_time"], window, tz)
    if not in_window:
        return _err(
            "window_exceeded",
            f"La ventana para reprogramar es de {window}h antes (faltan {remaining:.1f}h). "
            f"Por favor llama a la clínica.",
        )

    svc_row = appt["services"]
    pet_row = appt["pets"] or {}
    try:
        svc = resolve_service(svc_row["code"], pet_row.get("size"))
    except ValueError as e:
        return _err("service_resolution", str(e))

    try:
        new_start = datetime.fromisoformat(new_start_time)
    except ValueError:
        return _err("invalid_start_time", f"Formato de hora inválido: '{new_start_time}'.")
    if new_start.tzinfo is None:
        new_start = new_start.replace(tzinfo=tz)
    new_start = new_start.astimezone(tz)
    new_end = new_start + timedelta(minutes=svc.duration_min)

    if new_start.isoweekday() not in (settings.get("operating_days") or [1, 2, 3, 4, 5]):
        return _err("non_operating_day", "Ese día la clínica no atiende.")

    op = str(settings["opening_time"])
    cl = str(settings["closing_time"])
    op_h, op_m = (int(x) for x in op.split(":")[:2])
    cl_h, cl_m = (int(x) for x in cl.split(":")[:2])
    day_start = new_start.replace(hour=op_h, minute=op_m, second=0, microsecond=0)
    day_end = new_start.replace(hour=cl_h, minute=cl_m, second=0, microsecond=0)
    if new_start < day_start or new_end > day_end:
        return _err(
            "outside_hours",
            f"La cita debe iniciar y terminar dentro del horario {op}-{cl}.",
        )
    if new_start <= datetime.now(tz=tz):
        return _err("in_the_past", "Esa hora ya pasó. Elige un horario futuro.")

    chosen_room_id = appt["room_id"]
    if has_overlap(chosen_room_id, new_start, new_end, exclude_appt_id=appointment_id):
        rooms = (
            supabase.table("rooms")
            .select("id, name")
            .eq("room_type", svc.room_type)
            .eq("is_active", True)
            .order("name")
            .execute()
            .data
            or []
        )
        chosen_room_id = None
        for r in rooms:
            if not has_overlap(r["id"], new_start, new_end, exclude_appt_id=appointment_id):
                chosen_room_id = r["id"]
                break
        if not chosen_room_id:
            return _err(
                "no_room_available",
                "No hay sala libre en ese horario. ¿Te muestro otros slots?",
            )

    supabase.table("appointments").update(
        {
            "start_time": new_start.isoformat(),
            "end_time": new_end.isoformat(),
            "room_id": chosen_room_id,
        }
    ).eq("id", appointment_id).execute()

    return _ok(
        {
            "appointment_id": appointment_id,
            "new_start_time": new_start.isoformat(),
            "new_end_time": new_end.isoformat(),
            "room_id": chosen_room_id,
        }
    )


# =============================================================================
# Pagos simulados (Fase 6)
# =============================================================================


def list_my_pending_payments(tool_context: ToolContext) -> dict:
    """Lista las citas del cliente actual con pago pendiente.

    Devuelve `[{appointment_id, service_name, pet_name, start_time, amount, currency}]`.
    """
    supabase = get_supabase()
    client_id = _resolve_client_id(tool_context)
    if not client_id:
        return _ok([], note="client_not_registered")

    settings = (
        supabase.table("clinic_settings")
        .select("currency")
        .eq("id", 1)
        .single()
        .execute()
        .data
    )
    res = (
        supabase.table("appointments")
        .select(
            "id, start_time, status, total_amount, "
            "pets(name), services(name), payments(status, amount)"
        )
        .eq("client_id", client_id)
        .neq("status", "canceled")
        .order("start_time")
        .execute()
    )
    out = []
    for row in res.data or []:
        payment = row.get("payments")
        if isinstance(payment, list):
            payment = payment[0] if payment else None
        if not payment or payment.get("status") != "pending":
            continue
        out.append(
            {
                "appointment_id": row["id"],
                "pet_name": (row.get("pets") or {}).get("name"),
                "service_name": (row.get("services") or {}).get("name"),
                "start_time": row["start_time"],
                "amount": float(payment["amount"]) if payment.get("amount") else None,
                "currency": settings.get("currency") or "PEN",
            }
        )
    return _ok(out)


def get_payment_status(appointment_id: str, tool_context: ToolContext) -> dict:
    """Devuelve el estado del pago de una cita propia."""
    supabase = get_supabase()
    client_id = _resolve_client_id(tool_context)
    if not client_id:
        return _err("client_not_registered", "No tienes registro de cliente.")

    res = (
        supabase.table("appointments")
        .select(
            "id, client_id, total_amount, services(name), payments(status, amount, paid_at, method)"
        )
        .eq("id", appointment_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        return _err("appointment_not_found", "No encontré esa cita.")
    appt = res.data
    if appt["client_id"] != client_id:
        return _err("not_your_appointment", "Esa cita no es tuya.")

    payment = appt.get("payments")
    if isinstance(payment, list):
        payment = payment[0] if payment else None

    return _ok(
        {
            "appointment_id": appointment_id,
            "service": (appt.get("services") or {}).get("name"),
            "amount": float(appt["total_amount"]) if appt.get("total_amount") else None,
            "payment_status": (payment or {}).get("status"),
            "paid_at": (payment or {}).get("paid_at"),
            "method": (payment or {}).get("method"),
        }
    )


def register_simulated_payment(appointment_id: str, tool_context: ToolContext) -> dict:
    """Registra un pago simulado para una cita.

    Marca el `payments.status = 'paid'`, `paid_at = now()`, `method = 'simulated'`.
    Si no existía registro de pago, lo crea con el `total_amount` de la cita.
    """
    supabase = get_supabase()
    client_id = _resolve_client_id(tool_context)
    if not client_id:
        return _err("client_not_registered", "No tienes registro de cliente.")

    appt_res = (
        supabase.table("appointments")
        .select("id, client_id, status, total_amount")
        .eq("id", appointment_id)
        .maybe_single()
        .execute()
    )
    if not (appt_res and appt_res.data):
        return _err("appointment_not_found", "No encontré esa cita.")
    appt = appt_res.data
    if appt["client_id"] != client_id:
        return _err("not_your_appointment", "Esa cita no es tuya.")
    if appt["status"] == "canceled":
        return _err(
            "appointment_canceled",
            "Esa cita está cancelada, no se puede pagar.",
        )

    settings = (
        supabase.table("clinic_settings")
        .select("currency, timezone")
        .eq("id", 1)
        .single()
        .execute()
        .data
    )
    tz = ZoneInfo(settings.get("timezone") or "America/Lima")
    now_iso = datetime.now(tz=tz).isoformat()

    pay_res = (
        supabase.table("payments")
        .select("id, status, amount")
        .eq("appointment_id", appointment_id)
        .maybe_single()
        .execute()
    )

    if pay_res and pay_res.data:
        pay = pay_res.data
        if pay["status"] == "paid":
            return _ok(
                {
                    "appointment_id": appointment_id,
                    "payment_status": "paid",
                    "amount": float(pay["amount"]) if pay.get("amount") else None,
                    "currency": settings.get("currency") or "PEN",
                    "already_paid": True,
                }
            )
        if pay["status"] == "refunded":
            return _err(
                "already_refunded",
                "El pago de esta cita ya fue devuelto; no se puede volver a cobrar.",
            )
        supabase.table("payments").update(
            {"status": "paid", "method": "simulated", "paid_at": now_iso}
        ).eq("id", pay["id"]).execute()
        amount = float(pay["amount"]) if pay.get("amount") else None
    else:
        amount = float(appt["total_amount"]) if appt.get("total_amount") else 0.0
        supabase.table("payments").insert(
            {
                "appointment_id": appointment_id,
                "amount": amount,
                "status": "paid",
                "method": "simulated",
                "paid_at": now_iso,
            }
        ).execute()

    return _ok(
        {
            "appointment_id": appointment_id,
            "payment_status": "paid",
            "amount": amount,
            "currency": settings.get("currency") or "PEN",
            "paid_at": now_iso,
            "method": "simulated",
        }
    )


# =============================================================================
# Memoria persistente entre sesiones (Fase 7)
# =============================================================================


def get_my_summary(tool_context: ToolContext) -> dict:
    """Devuelve el resumen persistente del cliente actual (memoria entre sesiones).

    Útil al inicio de una conversación para recordar al usuario. Si no hay resumen,
    devuelve `data: null`.
    """
    supabase = get_supabase()
    user_id = _resolve_user_id(tool_context)
    res = (
        supabase.table("user_summaries")
        .select("user_id, summary, last_updated")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        return _ok(None)
    tool_context.state["user_summary"] = res.data["summary"]
    return _ok(res.data)


def update_my_summary(summary: str, tool_context: ToolContext) -> dict:
    """Actualiza/crea el resumen persistente del cliente actual.

    El resumen es un texto corto (máx ~500 caracteres) en tercera persona que captura
    información útil para futuras sesiones: nombres y especies de mascotas, último
    servicio agendado, preferencias notadas, etc.
    """
    if not summary or not summary.strip():
        return _err("empty_summary", "El resumen no puede estar vacío.")
    summary = summary.strip()[:1000]

    supabase = get_supabase()
    user_id = _resolve_user_id(tool_context)
    payload = {"user_id": user_id, "summary": summary}
    res = (
        supabase.table("user_summaries")
        .upsert(payload, on_conflict="user_id")
        .execute()
    )
    tool_context.state["user_summary"] = summary
    return _ok({"user_id": user_id, "summary": summary, "updated": True, "rows": len(res.data or [])})
