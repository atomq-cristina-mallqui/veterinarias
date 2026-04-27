"""Cálculo de slots disponibles para una fecha + servicio + tamaño de mascota.

Algoritmo:
  1. Leer `clinic_settings`.
  2. Validar que la fecha sea día operativo.
  3. Resolver servicio + duración (consultando services y service_durations).
  4. Listar rooms activos del room_type del servicio.
  5. Listar appointments activos (scheduled/completed) en esos rooms para ese día.
  6. Generar slots cada `slot_granularity_min` minutos entre opening y closing-duration.
  7. Excluir solapes; si la fecha es hoy, excluir slots ya pasados (más buffer).
  8. Devolver hasta `max_slots` ordenados por hora y luego por sala.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from vet_assistant.tools.supabase_client import get_supabase

NOW_BUFFER_MINUTES = 15  # No ofrecer slots que arranquen en menos de N minutos.


@dataclass
class ServiceInfo:
    id: str
    code: str
    name: str
    room_type: str
    duration_min: int
    price: float
    requires_pet_size: bool


@dataclass
class Slot:
    start: datetime
    end: datetime
    room_id: str
    room_name: str


def _load_settings() -> dict[str, Any]:
    res = (
        get_supabase()
        .table("clinic_settings")
        .select("*")
        .eq("id", 1)
        .single()
        .execute()
    )
    return res.data


def _parse_time(value: Any) -> time:
    if isinstance(value, time):
        return value
    s = str(value)
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def _parse_date(value: str) -> date_type:
    return date_type.fromisoformat(value)


def resolve_service(service_code: str, pet_size: Optional[str]) -> ServiceInfo:
    """Resuelve un service_code + pet_size a duración y precio aplicables.

    Lanza ValueError si el servicio no existe, está inactivo o falta tamaño cuando se
    requiere.
    """
    supabase = get_supabase()
    res = (
        supabase.table("services")
        .select("*")
        .eq("code", service_code)
        .eq("is_active", True)
        .maybe_single()
        .execute()
    )
    if not (res and res.data):
        raise ValueError(f"Servicio '{service_code}' no existe o está inactivo.")
    svc = res.data

    if svc["requires_pet_size"]:
        if not pet_size:
            raise ValueError(
                f"El servicio '{svc['name']}' requiere el tamaño de la mascota "
                f"(small/medium/large)."
            )
        dur_res = (
            supabase.table("service_durations")
            .select("duration_min, price")
            .eq("service_id", svc["id"])
            .eq("pet_size", pet_size)
            .maybe_single()
            .execute()
        )
        if not (dur_res and dur_res.data):
            raise ValueError(
                f"No hay tarifa para el servicio '{svc['name']}' con tamaño '{pet_size}'."
            )
        duration_min = int(dur_res.data["duration_min"])
        price = float(dur_res.data["price"])
    else:
        duration_min = int(svc["duration_default_min"])
        price = float(svc["price_default"])

    return ServiceInfo(
        id=svc["id"],
        code=svc["code"],
        name=svc["name"],
        room_type=svc["room_type"],
        duration_min=duration_min,
        price=price,
        requires_pet_size=bool(svc["requires_pet_size"]),
    )


def _list_active_rooms(room_type: str) -> list[dict]:
    res = (
        get_supabase()
        .table("rooms")
        .select("id, name, room_type, is_active")
        .eq("room_type", room_type)
        .eq("is_active", True)
        .order("name")
        .execute()
    )
    return res.data or []


def _list_appointments_in_window(
    room_ids: list[str],
    day_start: datetime,
    day_end: datetime,
) -> list[dict]:
    res = (
        get_supabase()
        .table("appointments")
        .select("id, room_id, start_time, end_time, status")
        .in_("room_id", room_ids)
        .gte("start_time", day_start.isoformat())
        .lt("start_time", day_end.isoformat())
        .in_("status", ["scheduled", "completed"])
        .execute()
    )
    return res.data or []


def _parse_hhmm_to_minutes(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    parts = s.split(":")
    hh = int(parts[0])
    mm = int(parts[1]) if len(parts) > 1 else 0
    return hh * 60 + mm


def list_available_slots_impl(
    target_date: str,
    service_code: str,
    pet_size: Optional[str] = None,
    max_slots: int = 0,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
) -> dict[str, Any]:
    """Implementación pura del cálculo. Devuelve dict serializable.

    Args:
        from_time: filtro inferior 'HH:MM' local (inclusive). Aplica antes del recorte
            por `max_slots`, así el rango pedido por el usuario nunca se pierde por
            haberse quedado sin cupo en el truncado.
        to_time: filtro superior 'HH:MM' local (exclusivo). Mismo comportamiento.

    Estructura:
        {
          "ok": bool,
          "service": {code, name, duration_min, price, room_type},
          "date": "YYYY-MM-DD",
          "timezone": "...",
          "slots": [{start_time, end_time, room_id, room_name}, ...],
          "error": optional str,
        }
    """
    try:
        settings = _load_settings()
    except Exception as e:
        return {"ok": False, "error": f"No se pudieron leer settings: {e}"}

    tz = ZoneInfo(settings.get("timezone") or "America/Lima")

    try:
        d = _parse_date(target_date)
    except Exception:
        return {"ok": False, "error": f"Fecha inválida: '{target_date}'. Usa formato YYYY-MM-DD."}

    iso_weekday = d.isoweekday()  # 1=Mon..7=Sun
    operating_days = settings.get("operating_days") or [1, 2, 3, 4, 5]
    if iso_weekday not in operating_days:
        return {
            "ok": False,
            "code": "non_operating_day",
            "error": (
                f"El {d.isoformat()} no es un día de atención. "
                f"Atendemos lunes a viernes."
            ),
        }

    try:
        svc = resolve_service(service_code, pet_size)
    except ValueError as e:
        return {"ok": False, "code": "service_resolution", "error": str(e)}

    rooms = _list_active_rooms(svc.room_type)
    if not rooms:
        return {
            "ok": False,
            "code": "no_rooms",
            "error": f"No hay salas activas para servicio tipo '{svc.room_type}'.",
        }

    opening = _parse_time(settings["opening_time"])
    closing = _parse_time(settings["closing_time"])
    granularity = int(settings["slot_granularity_min"])
    duration = timedelta(minutes=svc.duration_min)

    day_start = datetime.combine(d, opening, tzinfo=tz)
    day_end = datetime.combine(d, closing, tzinfo=tz)

    last_start = day_end - duration
    if last_start < day_start:
        return {
            "ok": False,
            "code": "service_too_long",
            "error": "El servicio no cabe en el horario de atención de ese día.",
        }

    room_ids = [r["id"] for r in rooms]
    by_room: dict[str, list[tuple[datetime, datetime]]] = {rid: [] for rid in room_ids}
    appointments = _list_appointments_in_window(room_ids, day_start, day_end)
    for appt in appointments:
        s = datetime.fromisoformat(appt["start_time"]).astimezone(tz)
        e = datetime.fromisoformat(appt["end_time"]).astimezone(tz)
        by_room.setdefault(appt["room_id"], []).append((s, e))

    now_local = datetime.now(tz=tz)
    not_before = now_local + timedelta(minutes=NOW_BUFFER_MINUTES) if d == now_local.date() else None

    from_minutes = _parse_hhmm_to_minutes(from_time)
    to_minutes = _parse_hhmm_to_minutes(to_time)

    slots: list[Slot] = []
    cursor = day_start
    step = timedelta(minutes=granularity)
    while cursor <= last_start:
        slot_end = cursor + duration
        cursor_minutes = cursor.hour * 60 + cursor.minute
        in_range = True
        if from_minutes is not None and cursor_minutes < from_minutes:
            in_range = False
        if in_range and to_minutes is not None and cursor_minutes >= to_minutes:
            in_range = False
        if in_range and (not_before is None or cursor >= not_before):
            for room in rooms:
                rid = room["id"]
                conflict = False
                for s, e in by_room.get(rid, []):
                    if cursor < e and slot_end > s:
                        conflict = True
                        break
                if not conflict:
                    # Guardamos todos los rooms libres en ese horario para soportar
                    # casos multi-mascota a la misma hora en salas distintas.
                    slots.append(
                        Slot(
                            start=cursor,
                            end=slot_end,
                            room_id=rid,
                            room_name=room["name"],
                        )
                    )
        cursor += step

    if max_slots and max_slots > 0:
        slots = slots[:max_slots]
    return {
        "ok": True,
        "service": {
            "code": svc.code,
            "name": svc.name,
            "duration_min": svc.duration_min,
            "price": svc.price,
            "room_type": svc.room_type,
        },
        "date": d.isoformat(),
        "timezone": str(tz),
        "slots": [
            {
                "start_time": s.start.isoformat(),
                "end_time": s.end.isoformat(),
                "room_id": s.room_id,
                "room_name": s.room_name,
            }
            for s in slots
        ],
    }


def has_overlap(room_id: str, start: datetime, end: datetime, exclude_appt_id: Optional[str] = None) -> bool:
    """Comprueba si un nuevo slot solaparía con otra cita activa en el room.

    Útil al crear o reprogramar (la BD también lo valida con EXCLUDE pero anticipamos
    el error para devolver mensaje amable).
    """
    q = (
        get_supabase()
        .table("appointments")
        .select("id, start_time, end_time, status")
        .eq("room_id", room_id)
        .in_("status", ["scheduled", "completed"])
        .lt("start_time", end.isoformat())
        .gt("end_time", start.isoformat())
    )
    res = q.execute()
    rows = res.data or []
    if exclude_appt_id:
        rows = [r for r in rows if r["id"] != exclude_appt_id]
    return bool(rows)
