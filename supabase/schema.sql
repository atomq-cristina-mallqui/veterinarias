-- =============================================================================
-- Schema: Clínica Veterinaria Patitas Felices
-- =============================================================================
-- Idempotente: puede ejecutarse varias veces sin error.
-- Ejecutar contra Supabase con `python scripts/init_db.py` o pegando en el
-- SQL Editor del dashboard.
-- =============================================================================

-- Extensiones
create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";
create extension if not exists "btree_gist";  -- para EXCLUDE de overlaps

-- -----------------------------------------------------------------------------
-- Tipos enumerados
-- -----------------------------------------------------------------------------
do $$ begin
  create type pet_species as enum ('dog', 'cat', 'other');
exception when duplicate_object then null; end $$;

do $$ begin
  create type pet_size as enum ('small', 'medium', 'large');
exception when duplicate_object then null; end $$;

do $$ begin
  create type room_type as enum ('grooming', 'medical');
exception when duplicate_object then null; end $$;

do $$ begin
  create type appointment_status as enum ('scheduled', 'completed', 'canceled', 'no_show');
exception when duplicate_object then null; end $$;

do $$ begin
  create type payment_status as enum ('pending', 'paid', 'refunded');
exception when duplicate_object then null; end $$;

do $$ begin
  create type payment_method as enum ('simulated', 'cash', 'card', 'transfer');
exception when duplicate_object then null; end $$;

-- -----------------------------------------------------------------------------
-- Tabla: clients
-- -----------------------------------------------------------------------------
create table if not exists clients (
  id          uuid primary key default gen_random_uuid(),
  user_id     text unique not null,
  full_name   text not null,
  phone       text,
  email       text,
  notes       text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists idx_clients_user_id on clients (user_id);

-- -----------------------------------------------------------------------------
-- Tabla: pets
-- -----------------------------------------------------------------------------
create table if not exists pets (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid not null references clients(id) on delete cascade,
  name        text not null,
  species     pet_species not null,
  breed       text,
  weight_kg   numeric(5, 2) check (weight_kg > 0),
  size        pet_size,
  birth_date  date,
  notes       text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists idx_pets_client_id on pets (client_id);

-- -----------------------------------------------------------------------------
-- Tabla: rooms
-- -----------------------------------------------------------------------------
create table if not exists rooms (
  id          uuid primary key default gen_random_uuid(),
  name        text unique not null,
  room_type   room_type not null,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

-- -----------------------------------------------------------------------------
-- Tabla: services
-- -----------------------------------------------------------------------------
create table if not exists services (
  id                    uuid primary key default gen_random_uuid(),
  code                  text unique not null,
  name                  text not null,
  description           text,
  room_type             room_type not null,
  duration_default_min  integer,
  price_default         numeric(10, 2),
  requires_pet_size     boolean not null default false,
  is_active             boolean not null default true,
  created_at            timestamptz not null default now()
);

-- -----------------------------------------------------------------------------
-- Tabla: service_durations (para servicios con tarifa por tamaño de mascota)
-- -----------------------------------------------------------------------------
create table if not exists service_durations (
  id            uuid primary key default gen_random_uuid(),
  service_id    uuid not null references services(id) on delete cascade,
  pet_size      pet_size not null,
  duration_min  integer not null check (duration_min > 0),
  price         numeric(10, 2) not null check (price >= 0),
  unique (service_id, pet_size)
);

create index if not exists idx_service_durations_service on service_durations (service_id);

-- -----------------------------------------------------------------------------
-- Tabla: appointments
-- -----------------------------------------------------------------------------
create table if not exists appointments (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete restrict,
  pet_id        uuid not null references pets(id)    on delete restrict,
  service_id    uuid not null references services(id) on delete restrict,
  room_id       uuid not null references rooms(id)    on delete restrict,
  start_time    timestamptz not null,
  end_time      timestamptz not null,
  status        appointment_status not null default 'scheduled',
  total_amount  numeric(10, 2),
  notes         text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint chk_appointment_time_order check (end_time > start_time)
);

create index if not exists idx_appt_client      on appointments (client_id);
create index if not exists idx_appt_pet         on appointments (pet_id);
create index if not exists idx_appt_room_time   on appointments (room_id, start_time);
create index if not exists idx_appt_status_time on appointments (status, start_time);

-- Evita que dos citas activas (scheduled/completed) se pisen en la misma sala.
alter table appointments drop constraint if exists no_overlapping_appointments;
alter table appointments
  add constraint no_overlapping_appointments
  exclude using gist (
    room_id with =,
    tstzrange(start_time, end_time, '[)') with &&
  ) where (status in ('scheduled', 'completed'));

-- -----------------------------------------------------------------------------
-- Tabla: payments (1:1 con appointments)
-- -----------------------------------------------------------------------------
create table if not exists payments (
  id              uuid primary key default gen_random_uuid(),
  appointment_id  uuid unique not null references appointments(id) on delete cascade,
  amount          numeric(10, 2) not null check (amount >= 0),
  status          payment_status not null default 'pending',
  method          payment_method not null default 'simulated',
  paid_at         timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists idx_payments_status on payments (status);

-- -----------------------------------------------------------------------------
-- Tabla: user_summaries (memoria persistente entre sesiones)
-- -----------------------------------------------------------------------------
create table if not exists user_summaries (
  user_id       text primary key,
  summary       text not null,
  last_updated  timestamptz not null default now()
);

-- -----------------------------------------------------------------------------
-- Tabla: clinic_settings (1 fila)
-- -----------------------------------------------------------------------------
create table if not exists clinic_settings (
  id                          integer primary key default 1,
  opening_time                time not null default '09:00',
  closing_time                time not null default '17:00',
  operating_days              integer[] not null default '{1,2,3,4,5}'::integer[], -- 1=Mon..7=Sun
  cancellation_window_hours   integer not null default 2,
  reschedule_window_hours     integer not null default 2,
  slot_granularity_min        integer not null default 15,
  timezone                    text not null default 'America/Lima',
  currency                    text not null default 'PEN',
  updated_at                  timestamptz not null default now(),
  constraint clinic_settings_singleton check (id = 1)
);

-- -----------------------------------------------------------------------------
-- Trigger genérico: auto-update updated_at
-- -----------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

do $$ begin
  create trigger trg_clients_updated     before update on clients     for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger trg_pets_updated        before update on pets        for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger trg_appt_updated        before update on appointments for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger trg_payments_updated    before update on payments    for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger trg_settings_updated    before update on clinic_settings for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
