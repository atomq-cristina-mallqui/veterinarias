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

Patrón **coordinador** con sub-agentes especializados invocados como tools (`AgentTool`):

```
                      RootAgent (Lucy)
                            │
   ┌──────────┬─────────────┼─────────────┬─────────────┐
   ▼          ▼             ▼             ▼             ▼             ▼
chitchat   faq        client_pet    scheduling   management    payment
                          │              │           │            │
                          └────── tools Supabase ────┴────────────┘
```

- El `RootAgent` es el único que conversa con el usuario y reformula las salidas de los
sub-agentes en su propia voz.
- Cada sub-agente tiene un prompt corto y un set acotado de tools.
- Las tools son funciones Python que ADK introspecciona automáticamente y persisten en
Supabase.
- El estado de sesión (`tool_context.state`) guarda `user_id`, `client_id`,
`selected_pet_id`, `last_quoted_slot`, etc., para mantener el contexto entre turnos.
- Memoria persistente entre sesiones en la tabla `user_summaries` (resumen de
preferencias, mascotas, últimas citas).

## Estructura

```
vet_adk/
  vet_assistant/                   # paquete del agente (lo detecta `adk web`)
    agent.py                       # root_agent + InstructionProvider con fecha y memoria
    callbacks.py                   # init_session_state (carga client_id y resumen)
    config.py                      # carga .env, proveedor/modelo LLM, constantes
    sub_agents/                    # 6 sub-agentes especializados
    tools/
      supabase_client.py           # cliente Supabase singleton
      supabase_tools.py            # ~14 tools expuestas a los sub-agentes
      availability.py              # cálculo de slots libres
      pet_size_rules.py            # mapeo peso → tamaño
    prompts/                       # un .md por agente
  supabase/
    schema.sql                     # CREATE TABLE de las 9 tablas
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
- `SUPABASE_DB_URL`: connection string Postgres (solo para inicializar la BD)

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

### 4. Correr ADK Web

Desde la raíz del repo:

```bash
adk web
```

Abre [http://localhost:8000](http://localhost:8000) → selecciona el agente `**vet_assistant**` → crea una sesión
con `user_id = user_demo_1` (ya existe en el seed con la cliente Cristina Ramos y sus
mascotas Toby y Mishi).

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

