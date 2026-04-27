# Test Plan - WhatsApp Vet Assistant

Plan minimo para validar cada cambio antes de push/deploy.

## A) Pre-push (local)

### A.1 Salud tecnica

- `python -m compileall vet_assistant`
- Lints sin errores en archivos modificados.
- Revisión de diff: sin cambios accidentales fuera de alcance.

### A.2 Casos funcionales criticos

1. Onboarding primera cita:
   - El usuario elige cupo.
   - Bot explica onboarding en una frase.
   - Pide nombre + datos de mascota.
   - No pide telefono ni correo.

2. Usuario ya registrado:
   - No pregunta "si la mascota ya esta registrada".
   - No pregunta size si ya existe en `pets.size`.

3. Agendamiento:
   - Hora confirmada coincide con hora en DB convertida a Lima.
   - Estado queda `scheduled` y pago `pending`.

4. Adicional grooming:
   - Si no cabe en la hora exacta, propone alternativas cercanas.
   - No contradice horarios de la cita base en el mismo hilo.

5. Pago:
   - Registra pago una sola vez.
   - No duplica cobros.

## B) Post-deploy (Railway)

### B.1 Salud del servicio

- `GET /health` devuelve `{"status":"ok"}`.
- Webhook verificado en Meta.

### B.2 Observabilidad en logs

Por cada mensaje entrante revisar:

- request recibido en `/webhook/whatsapp`
- una sola respuesta enviada
- sin errores `stale session`
- sin excepciones no controladas

### B.3 Latencia

Medir 10-20 turnos:

- p50 < 4s
- p95 < 8s
- sin outliers > 15s (salvo incidente externo)

## C) Queries SQL de validacion

### C.1 Mascotas por usuario

```sql
select
  c.user_id,
  c.full_name,
  p.name,
  p.species,
  p.weight_kg,
  p.size
from pets p
join clients c on c.id = p.client_id
where c.user_id = '<WA_ID>'
order by p.name;
```

### C.2 Horarios en Lima

```sql
select
  id,
  start_time,
  start_time at time zone 'America/Lima' as start_lima,
  end_time,
  end_time at time zone 'America/Lima' as end_lima,
  status
from appointments
where status = 'scheduled'
order by start_time desc
limit 20;
```

### C.3 Duplicados potenciales de cita

```sql
select
  client_id,
  pet_id,
  service_id,
  start_time,
  count(*) as n
from appointments
where status = 'scheduled'
group by client_id, pet_id, service_id, start_time
having count(*) > 1
order by n desc;
```

## D) Criterio de salida

Se autoriza push/deploy solo si:

- todos los casos A y B pasan,
- queries C sin hallazgos criticos,
- no hay contradicciones de horario ni duplicados en pruebas end-to-end.
