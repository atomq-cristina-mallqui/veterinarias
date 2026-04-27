# Release Criteria - WhatsApp Vet Assistant

Este documento define la **Definition of Done** para considerar una version
"lista para push" y "lista para deploy" en el canal WhatsApp.

## 1) Criterios de experiencia (UX)

- Respuestas breves (1-3 oraciones), claras y sin formularios largos.
- No repreguntar datos ya confirmados en el mismo flujo.
- Onboarding breve y explicito solo cuando corresponde.
- No pedir telefono en WhatsApp (se usa `wa_id`).
- No pedir correo en onboarding de primera cita.

## 2) Criterios de datos y consistencia

- `user_id = wa_id` para identidad del cliente.
- `clients.phone` se completa con `wa_id` por defecto en flujo WhatsApp.
- Horarios mostrados al usuario en zona `America/Lima`.
- No contradicciones de hora para la misma cita en una conversacion.
- No crear citas duplicadas para el mismo `pet_id + service + start_time`.

## 3) Criterios de robustez

- Sin excepciones `stale session` en logs durante pruebas.
- Sin respuestas duplicadas para el mismo `message_id`.
- Flujo 1:1: un mensaje de usuario produce una sola respuesta del bot.
- Error handling amable (sin stack traces ni codigos internos al usuario).

## 4) Criterios de rendimiento

- p50 de respuesta < 4s.
- p95 de respuesta < 8s.
- Ningun turno > 15s salvo falla externa (API proveedor, red, etc.).

## 5) Criterios de arquitectura

- Webhook de WhatsApp pasa por `root_agent` (no por prompt directo).
- Sub-agentes y tools se usan como fuente de verdad para agenda/pagos/mascotas.
- Memoria persistente y sesiones operativas en Supabase.
- README actualizado con la arquitectura vigente.

## 6) Gate final de release

Para cerrar un release, todos los checks de `TEST_PLAN.md` deben estar en estado
OK y no debe haber hallazgos criticos abiertos.
