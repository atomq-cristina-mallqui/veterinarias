# Lucy — Asistente Veterinario Multi-Agente

Asistente conversacional para la **Clínica Veterinaria Patitas Felices**, construido con
[Google ADK](https://adk.dev) + OpenAI (vía LiteLLM) + Supabase.

## ¿Qué hace?

Permite, vía un chat conversacional en español:

- Saludar de forma personalizada (recuerda al cliente entre sesiones).
- Responder preguntas frecuentes sobre la clínica.
- Registrar al cliente y a sus mascotas (calcula tamaño de perro automáticamente).
- Consultar disponibilidad y agendar citas (consulta general, vacunación, baño,
peluquería) en cualquiera de las 5 salas (4 grooming + 1 médica).
- Listar las citas del cliente, reprogramar y cancelar (política flexible: hasta 2h
antes).
- Procesar pagos simulados.
- Mantener una conversación amena, proactiva y con contexto persistente.

## Arquitectura

La arquitectura actual está optimizada para canal WhatsApp + backend único en Railway:

```text
WhatsApp User
    |
    v
Meta WhatsApp Cloud API
    |
    v
Webhook (Railway)  ->  GET /webhook/whatsapp (verify)
    |               ->  POST /webhook/whatsapp (mensajes entrantes)
    v
vet_assistant/whatsapp_app.py
    |
    v
ADK Runner (root_agent)
    |
    +--> sub_agents (faq, chitchat, onboarding, client_pet, scheduling, appointment_management, payment)
    |
    +--> tools Supabase (citas, clientes, mascotas, pagos, disponibilidad)
    |
    +--> Session Service (DatabaseSessionService)
            | (tablas ADK en Supabase: sessions, events, adk_internal_metadata)
            v
Supabase Postgres
```

### Capas de memoria y datos

- **Datos operativos**: `clients`, `pets`, `appointments`, `payments`, etc.
- **Memoria resumida entre sesiones**: `user_summaries`.
- **Historial conversacional turno a turno (ADK)**: tablas `sessions` y `events`.
- **Estado de sesión**: `tool_context.state` (`user_id`, `client_id`,
`selected_pet_id`, `last_quoted_slot`, `client_phone`, etc.).

### Principio clave

- El `RootAgent` es el único que conversa con el usuario.
- Los sub-agentes se invocan como tools y Lucy reformula la respuesta final.
- En WhatsApp, la identidad se basa en `wa_id` (número): `user_id=wa_id`.
- `session_id` se resuelve por canal con esta prioridad:
  1) `session_id` del payload (si llega),
  2) nuevo `session_id` por comando `unsubscribe-session`,
  3) rotación por inactividad (>2 horas),
  4) reutilización de la última sesión activa.
- Durante onboarding por WhatsApp, el teléfono de registro se toma del canal (`wa_id`)
  y no se solicita correo.

## Estructura

```
vet_adk/
  vet_assistant/                   # paquete del agente (lo detecta `adk web`)
    agent.py                       # root_agent + InstructionProvider con fecha y memoria
    callbacks.py                   # init_session_state (carga client_id y resumen)
    config.py                      # carga .env, proveedor/modelo LLM, constantes
    whatsapp_app.py                # webhook WhatsApp (Meta) + Runner ADK
    sub_agents/                    # 6 sub-agentes especializados
    tools/
      supabase_client.py           # cliente Supabase singleton
      supabase_tools.py            # ~14 tools expuestas a los sub-agentes
      availability.py              # cálculo de slots libres
      pet_size_rules.py            # mapeo peso → tamaño
    prompts/                       # un .md por agente
  supabase/
    schema.sql                     # CREATE TABLE de tablas de negocio + user_summaries
    seed.sql                       # datos de muestra (3 clientes, 5 mascotas, 4 citas)
  scripts/init_db.py               # aplica schema+seed contra Supabase
```

## Setup

### 1. Dependencias

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Variables de entorno

Copia `.env.example` a `.env` y completa:

- `OPENAI_API_KEY`: API key de OpenAI.
- `LLM_PROVIDER`: `openai` (default) o `gemini`.
- `OPENAI_MODEL`: modelo OpenAI, por defecto `gpt-4o-mini`.
- `GOOGLE_API_KEY`: opcional, solo si quieres usar fallback Gemini.
- `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`: tu proyecto Supabase
- `SUPABASE_DB_URL`: connection string Postgres (inicializar BD + sesiones ADK en DB)
- `WHATSAPP_ACCESS_TOKEN`: token de WhatsApp Cloud API (Meta)
- `WHATSAPP_PHONE_NUMBER_ID`: id del número de WhatsApp en Meta
- `WHATSAPP_VERIFY_TOKEN`: token para validar webhook de Meta
- `WHATSAPP_API_VERSION`: por defecto `v23.0`

### 3. Inicializar la base de datos

Tienes 3 opciones:

**Opción A — script local** (requiere `SUPABASE_DB_URL` en `.env`):

```bash
python scripts/init_db.py            # aplica schema + seed + verifica conteos
python scripts/init_db.py --verify   # solo verifica conteos
```

**Opción B — SQL Editor de Supabase**: pega `supabase/schema.sql` y luego
`supabase/seed.sql` en [https://supabase.com/dashboard/project/_/sql/new](https://supabase.com/dashboard/project/_/sql/new)

**Opción C — MCP de Supabase desde el agente IDE**: pídele al asistente que aplique el
schema y seed con su MCP de Supabase.

### 4. Correr local (dos modos)

#### Modo A: ADK Web (debug / playground)

Desde la raíz del repo:

```bash
adk web .
```

Abre [http://localhost:8000](http://localhost:8000) → selecciona el agente `**vet_assistant**` → crea una sesión
con `user_id = user_demo_1` (ya existe en el seed con la cliente Cristina Ramos y sus
mascotas Toby y Mishi).

#### Modo B: Webhook WhatsApp local (backend HTTP)

```bash
uvicorn vet_assistant.whatsapp_app:app --host 0.0.0.0 --port 8000 --reload
```

Checks rápidos:

- `GET http://localhost:8000/health` -> `{"status":"ok"}`
- `GET /webhook/whatsapp?...` debe devolver `hub.challenge` en texto plano.

Para probar con Meta en local necesitas túnel (ej. ngrok).

### 5. Deploy en Railway (producción)

Este repo está preparado para Railway con:

- `railpack.json` (`provider: python`)
- `startCommand`: `uvicorn vet_assistant.whatsapp_app:app --host 0.0.0.0 --port $PORT`

Pasos:

1. Conecta el repo en Railway.
2. Configura variables de entorno (`OPENAI_*`, `SUPABASE_*`, `WHATSAPP_*`).
3. Verifica `https://<tu-dominio>.up.railway.app/health`.
4. En Meta configura webhook:
  - URL: `https://<tu-dominio>.up.railway.app/webhook/whatsapp`
  - Verify token: mismo valor de `WHATSAPP_VERIFY_TOKEN`
  - Suscripción mínima: campo `messages`

## Flujo WhatsApp end-to-end

1. Usuario envía mensaje en WhatsApp.
2. Meta envía `POST` al webhook.
3. `whatsapp_app.py` extrae `wa_id` y texto.
4. Resuelve `session_id` (payload/timeout/reset) y crea/recupera sesión ADK con
   `user_id=wa_id` en `DatabaseSessionService`.
5. Ejecuta `root_agent` con sub-agentes/tools.
6. Lee/escribe Supabase (citas, clientes, memoria).
7. Envía respuesta por Graph API a WhatsApp.

## Tablas en Supabase que debes ver

### Tablas de negocio (propias del proyecto)

- `clients`
- `pets`
- `appointments`
- `payments`
- `services`
- `service_durations`
- `rooms`
- `clinic_settings`
- `user_summaries`

### Tablas de sesión conversacional (creadas por ADK)

- `sessions`
- `events`
- `adk_internal_metadata`

## Quality Gates

Para mantener calidad estable antes de push/deploy:

- Criterios de release: `RELEASE_CRITERIA.md`
- Plan de pruebas y validaciones SQL: `TEST_PLAN.md`

Recomendación: ejecutar ese checklist en cada cambio de prompts, tools o webhook.

## Datos de muestra incluidos

- **3 clientes**: `user_demo_1` (Cristina Ramos), `user_demo_2` (Carlos Pérez),
`user_demo_3` (María Quispe).
- **5 mascotas**: Toby (perro mediano), Mishi (gata), Rocky (perro grande), Luna (perro
pequeño), Coco (conejo).
- **4 servicios**: consulta general (S/. 50), vacunación (S/. 60), baño (S/. 35/50/70),
peluquería (S/. 45/65/85).
- **5 salas**: Sala 1–4 (grooming), Consulta Médica.
- **4 citas de ejemplo**: 1 completada+pagada (ayer), 2 programadas (mañana, pasado),
1 cancelada.

## Flujos de prueba

Una vez en `adk web` con `user_id = user_demo_1`:

1. **Saludo con memoria**: solo escribe "hola" → Lucy te saluda por nombre y referencia
  tus mascotas.
2. **FAQ**: "¿cuánto cuesta el baño de un perro grande?" → responde S/. 70.
3. **Agendar**: "quiero agendar un baño para Toby el martes" → propone slots y crea cita.
4. **Listar**: "qué citas tengo" → muestra la cita creada.
5. **Pagar**: "quiero pagar mi cita" → registra pago simulado.
6. **Reprogramar**: "cambia mi cita a las 14:00" → busca slot y mueve.
7. **Cancelar**: "cancela mi cita" → cancela (si es a >2h).

Para probar el caso de cliente nuevo, crea una sesión con `user_id = user_nuevo_99`.

## Probar como otro usuario (sesiones independientes)

Cada sesión nueva en ADK Web arranca por defecto con un **usuario anónimo
aleatorio** (`anon_xxxxxxxx`), sin memoria persistente. Esto permite simular
múltiples clientes distintos sin reiniciar el servidor.

Tres formas de elegir el usuario de la sesión:

1. **Sesión limpia (default)**: pulsa `New Session` en ADK Web y empieza a
  chatear. Lucy te tratará como un cliente nuevo y no recordará nada de
   sesiones previas.
2. **Cliente existente del seed**: antes del primer mensaje, abre la pestaña
  `State` y agrega `user_id = "user_demo_1"` (Cristina Ramos) o
   `user_demo_2` / `user_demo_3`. Lucy te saludará por nombre y recordará tus
   mascotas y citas.
3. **Cliente nuevo identificable**: en la pestaña `State`, escribe un
  `user_id` arbitrario (ej. `cliente_juan`). Persistirá entre sesiones que
   uses ese mismo `user_id`.

El prefijo de los usuarios anónimos se puede cambiar con la variable
`ANON_USER_PREFIX` en `.env` (por defecto `anon_`).

## Modelo y configuración

- Por defecto usa OpenAI con `LLM_PROVIDER=openai` y `OPENAI_MODEL=gpt-4o-mini`.
- Si quieres volver a Gemini: `LLM_PROVIDER=gemini` y `GEMINI_MODEL=gemini-2.5-flash`.
- Zona horaria: `America/Lima` (cámbiala con `CLINIC_TIMEZONE`).
- Moneda: `PEN` (cámbiala con `CLINIC_CURRENCY` o en la tabla `clinic_settings`).
- Ventana de cancelación/reprogramación, días operativos y horas de atención son
**configurables** desde la tabla `clinic_settings` sin tocar código.

## Estado por fases

- Fase 0 — Setup, agente "hola mundo" en ADK Web
- Fase 1 — Esquema y datos de muestra en Supabase
- Fase 2 — Sub-agentes FAQ + ChitChat
- Fase 3 — ClientPetAgent (registro de cliente y mascotas)
- Fase 4 — SchedulingAgent (agendar citas)
- Fase 5 — AppointmentManagementAgent (ver / reprogramar / cancelar)
- Fase 6 — PaymentAgent (pago simulado)
- Fase 7 — Memoria persistente entre sesiones
- Fase 8 — Pulido conversacional (fecha inyectada, edge cases, tono proactivo)

