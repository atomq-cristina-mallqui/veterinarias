-- =============================================================================
-- Seed: datos de muestra para Patitas Felices
-- =============================================================================
-- Idempotente: usa UUIDs fijos y `on conflict do nothing/update`.
-- Las fechas de citas se calculan relativas a CURRENT_DATE para que siempre haya
-- ejemplos pasados, presentes y futuros sin importar cuándo se ejecute el seed.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- clinic_settings
-- -----------------------------------------------------------------------------
insert into clinic_settings (id, opening_time, closing_time, operating_days,
                             cancellation_window_hours, reschedule_window_hours,
                             slot_granularity_min, timezone, currency)
values (1, '09:00', '17:00', '{1,2,3,4,5}'::integer[], 2, 2, 15, 'America/Lima', 'PEN')
on conflict (id) do update set
  opening_time              = excluded.opening_time,
  closing_time              = excluded.closing_time,
  operating_days            = excluded.operating_days,
  cancellation_window_hours = excluded.cancellation_window_hours,
  reschedule_window_hours   = excluded.reschedule_window_hours,
  slot_granularity_min      = excluded.slot_granularity_min,
  timezone                  = excluded.timezone,
  currency                  = excluded.currency;

-- -----------------------------------------------------------------------------
-- rooms (4 grooming + 1 medical)
-- -----------------------------------------------------------------------------
insert into rooms (id, name, room_type, is_active) values
  ('11111111-1111-1111-1111-111111110001', 'Sala 1',           'grooming', true),
  ('11111111-1111-1111-1111-111111110002', 'Sala 2',           'grooming', true),
  ('11111111-1111-1111-1111-111111110003', 'Sala 3',           'grooming', true),
  ('11111111-1111-1111-1111-111111110004', 'Sala 4',           'grooming', true),
  ('11111111-1111-1111-1111-111111110005', 'Consulta Médica',  'medical',  true)
on conflict (id) do update set
  name      = excluded.name,
  room_type = excluded.room_type,
  is_active = excluded.is_active;

-- -----------------------------------------------------------------------------
-- services
-- -----------------------------------------------------------------------------
insert into services (id, code, name, description, room_type, duration_default_min,
                      price_default, requires_pet_size, is_active) values
  ('22222222-2222-2222-2222-222222220001', 'consulta_general',
    'Consulta general',
    'Evaluación clínica general en sala de consulta médica.',
    'medical', 30, 50.00, false, true),

  ('22222222-2222-2222-2222-222222220002', 'vacunacion',
    'Vacunación',
    'Aplicación de vacuna y revisión rápida en sala médica.',
    'medical', 15, 60.00, false, true),

  ('22222222-2222-2222-2222-222222220003', 'bano',
    'Baño',
    'Baño con shampoo según pelaje. Duración y precio según tamaño.',
    'grooming', null, null, true, true),

  ('22222222-2222-2222-2222-222222220004', 'peluqueria',
    'Peluquería',
    'Corte, secado y arreglo de pelaje. Duración y precio según tamaño.',
    'grooming', null, null, true, true)
on conflict (id) do update set
  code                  = excluded.code,
  name                  = excluded.name,
  description           = excluded.description,
  room_type             = excluded.room_type,
  duration_default_min  = excluded.duration_default_min,
  price_default         = excluded.price_default,
  requires_pet_size     = excluded.requires_pet_size,
  is_active             = excluded.is_active;

-- -----------------------------------------------------------------------------
-- Servicios adicionales de grooming (add-ons)
-- Duración y precio fijos, no dependen del tamaño de la mascota.
-- Se ofrecen como upsell tras agendar baño o peluquería.
-- -----------------------------------------------------------------------------
insert into services (id, code, name, description, room_type, duration_default_min,
                      price_default, requires_pet_size, is_active) values
  ('22222222-2222-2222-2222-222222220005', 'GROOM_PAW_TRIM',
    'Corte de plantares',
    'Corte del pelo entre las almohadillas (adicional de grooming).',
    'grooming', 10, 15.00, false, true),

  ('22222222-2222-2222-2222-222222220006', 'GROOM_DESHED',
    'Deslanado',
    'Tratamiento de deslanado para reducir muda (adicional de grooming).',
    'grooming', 20, 40.00, false, true),

  ('22222222-2222-2222-2222-222222220007', 'GROOM_MASK',
    'Mascarilla hidratante',
    'Mascarilla hidratante para pelaje (adicional de grooming).',
    'grooming', 30, 35.00, false, true)
on conflict (id) do update set
  code                  = excluded.code,
  name                  = excluded.name,
  description           = excluded.description,
  room_type             = excluded.room_type,
  duration_default_min  = excluded.duration_default_min,
  price_default         = excluded.price_default,
  requires_pet_size     = excluded.requires_pet_size,
  is_active             = excluded.is_active;

-- -----------------------------------------------------------------------------
-- service_durations (solo baño y peluquería)
-- -----------------------------------------------------------------------------
insert into service_durations (id, service_id, pet_size, duration_min, price) values
  -- Baño
  ('33333333-3333-3333-3333-333333330001', '22222222-2222-2222-2222-222222220003', 'small',  30, 35.00),
  ('33333333-3333-3333-3333-333333330002', '22222222-2222-2222-2222-222222220003', 'medium', 60, 50.00),
  ('33333333-3333-3333-3333-333333330003', '22222222-2222-2222-2222-222222220003', 'large',  90, 70.00),
  -- Peluquería
  ('33333333-3333-3333-3333-333333330004', '22222222-2222-2222-2222-222222220004', 'small',  30, 45.00),
  ('33333333-3333-3333-3333-333333330005', '22222222-2222-2222-2222-222222220004', 'medium', 60, 65.00),
  ('33333333-3333-3333-3333-333333330006', '22222222-2222-2222-2222-222222220004', 'large',  90, 85.00)
on conflict (id) do update set
  service_id    = excluded.service_id,
  pet_size      = excluded.pet_size,
  duration_min  = excluded.duration_min,
  price         = excluded.price;

-- -----------------------------------------------------------------------------
-- clients
-- -----------------------------------------------------------------------------
insert into clients (id, user_id, full_name, phone, email, notes) values
  ('44444444-4444-4444-4444-444444440001', 'user_demo_1', 'Cristina Ramos',
    '+51 987654321', 'cristina@example.com',
    'Cliente frecuente. Prefiere mañanas.'),
  ('44444444-4444-4444-4444-444444440002', 'user_demo_2', 'Carlos Pérez',
    '+51 912345678', 'carlos@example.com',
    'Vive cerca de la clínica.'),
  ('44444444-4444-4444-4444-444444440003', 'user_demo_3', 'María Quispe',
    '+51 956781234', 'maria@example.com',
    NULL)
on conflict (id) do update set
  user_id   = excluded.user_id,
  full_name = excluded.full_name,
  phone     = excluded.phone,
  email     = excluded.email,
  notes     = excluded.notes;

-- -----------------------------------------------------------------------------
-- pets
-- -----------------------------------------------------------------------------
insert into pets (id, client_id, name, species, breed, weight_kg, size, birth_date, notes) values
  ('55555555-5555-5555-5555-555555550001', '44444444-4444-4444-4444-444444440001',
    'Toby',  'dog',   'Beagle',          18.0, 'medium', '2021-03-15',
    'Le gusta el champú de avena.'),
  ('55555555-5555-5555-5555-555555550002', '44444444-4444-4444-4444-444444440001',
    'Mishi', 'cat',   'Doméstico',        4.5, 'small',  '2022-07-10',
    'Tímida con desconocidos.'),
  ('55555555-5555-5555-5555-555555550003', '44444444-4444-4444-4444-444444440002',
    'Rocky', 'dog',   'Labrador',        32.0, 'large',  '2019-11-02',
    'Muy activo, sin alergias conocidas.'),
  ('55555555-5555-5555-5555-555555550004', '44444444-4444-4444-4444-444444440003',
    'Luna',  'dog',   'Shih Tzu',         7.0, 'small',  '2023-01-20',
    NULL),
  ('55555555-5555-5555-5555-555555550005', '44444444-4444-4444-4444-444444440003',
    'Coco',  'other', 'Conejo holandés',  1.8, 'small',  '2023-09-05',
    'Manejar con cuidado.')
on conflict (id) do update set
  client_id   = excluded.client_id,
  name        = excluded.name,
  species     = excluded.species,
  breed       = excluded.breed,
  weight_kg   = excluded.weight_kg,
  size        = excluded.size,
  birth_date  = excluded.birth_date,
  notes       = excluded.notes;

-- -----------------------------------------------------------------------------
-- appointments (fechas relativas; se calcula próximo lunes-viernes)
-- -----------------------------------------------------------------------------
-- Helper: trasladar a próximo día hábil si cae en sábado/domingo.
-- Usamos directamente fechas concretas relativas al CURRENT_DATE.
do $$
declare
  v_yesterday    date := current_date - 1;
  v_tomorrow     date := current_date + 1;
  v_in_two_days  date := current_date + 2;
  v_in_three     date := current_date + 3;
begin
  -- Cita 1: Toby (Cristina) - Baño - AYER - completada y pagada
  insert into appointments (id, client_id, pet_id, service_id, room_id,
                            start_time, end_time, status, total_amount, notes)
  values (
    '66666666-6666-6666-6666-666666660001',
    '44444444-4444-4444-4444-444444440001',
    '55555555-5555-5555-5555-555555550001',
    '22222222-2222-2222-2222-222222220003',
    '11111111-1111-1111-1111-111111110001',
    (v_yesterday::text || ' 10:00')::timestamptz,
    (v_yesterday::text || ' 11:00')::timestamptz,
    'completed', 50.00, 'Servicio realizado sin novedad.'
  )
  on conflict (id) do update set
    start_time   = excluded.start_time,
    end_time     = excluded.end_time,
    status       = excluded.status,
    total_amount = excluded.total_amount,
    notes        = excluded.notes;

  -- Cita 2: Mishi (Cristina) - Consulta general - MAÑANA 11:00 - scheduled
  insert into appointments (id, client_id, pet_id, service_id, room_id,
                            start_time, end_time, status, total_amount, notes)
  values (
    '66666666-6666-6666-6666-666666660002',
    '44444444-4444-4444-4444-444444440001',
    '55555555-5555-5555-5555-555555550002',
    '22222222-2222-2222-2222-222222220001',
    '11111111-1111-1111-1111-111111110005',
    (v_tomorrow::text || ' 11:00')::timestamptz,
    (v_tomorrow::text || ' 11:30')::timestamptz,
    'scheduled', 50.00, 'Control de rutina.'
  )
  on conflict (id) do update set
    start_time   = excluded.start_time,
    end_time     = excluded.end_time,
    status       = excluded.status,
    total_amount = excluded.total_amount,
    notes        = excluded.notes;

  -- Cita 3: Rocky (Carlos) - Peluquería - PASADO MAÑANA 14:00 - scheduled
  insert into appointments (id, client_id, pet_id, service_id, room_id,
                            start_time, end_time, status, total_amount, notes)
  values (
    '66666666-6666-6666-6666-666666660003',
    '44444444-4444-4444-4444-444444440002',
    '55555555-5555-5555-5555-555555550003',
    '22222222-2222-2222-2222-222222220004',
    '11111111-1111-1111-1111-111111110002',
    (v_in_two_days::text || ' 14:00')::timestamptz,
    (v_in_two_days::text || ' 15:30')::timestamptz,
    'scheduled', 85.00, 'Corte de verano.'
  )
  on conflict (id) do update set
    start_time   = excluded.start_time,
    end_time     = excluded.end_time,
    status       = excluded.status,
    total_amount = excluded.total_amount,
    notes        = excluded.notes;

  -- Cita 4: Luna (María) - Vacunación - en 3 días - CANCELADA
  insert into appointments (id, client_id, pet_id, service_id, room_id,
                            start_time, end_time, status, total_amount, notes)
  values (
    '66666666-6666-6666-6666-666666660004',
    '44444444-4444-4444-4444-444444440003',
    '55555555-5555-5555-5555-555555550004',
    '22222222-2222-2222-2222-222222220002',
    '11111111-1111-1111-1111-111111110005',
    (v_in_three::text || ' 09:30')::timestamptz,
    (v_in_three::text || ' 09:45')::timestamptz,
    'canceled', 60.00, 'Cancelada por el cliente.'
  )
  on conflict (id) do update set
    start_time   = excluded.start_time,
    end_time     = excluded.end_time,
    status       = excluded.status,
    total_amount = excluded.total_amount,
    notes        = excluded.notes;
end $$;

-- -----------------------------------------------------------------------------
-- payments (uno pagado, uno pendiente)
-- -----------------------------------------------------------------------------
insert into payments (id, appointment_id, amount, status, method, paid_at) values
  ('77777777-7777-7777-7777-777777770001',
    '66666666-6666-6666-6666-666666660001', 50.00, 'paid',   'simulated', now() - interval '1 day'),
  ('77777777-7777-7777-7777-777777770002',
    '66666666-6666-6666-6666-666666660003', 85.00, 'pending', 'simulated', null)
on conflict (id) do update set
  amount  = excluded.amount,
  status  = excluded.status,
  method  = excluded.method,
  paid_at = excluded.paid_at;

-- -----------------------------------------------------------------------------
-- user_summaries (memoria persistente de ejemplo)
-- -----------------------------------------------------------------------------
insert into user_summaries (user_id, summary) values
  ('user_demo_1',
   'Cristina Ramos, cliente frecuente. Tiene a Toby (perro Beagle, 18kg, mediano) ' ||
   'y a Mishi (gata doméstica, 4.5kg). Prefiere citas en la mañana. Última cita: ' ||
   'baño de Toby (completada y pagada).')
on conflict (user_id) do update set
  summary      = excluded.summary,
  last_updated = now();
