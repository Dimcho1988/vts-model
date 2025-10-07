
-- Postgres schema for Strava add-on

create table if not exists workouts (
  id bigserial primary key,
  athlete_id bigint not null,
  activity_id bigint unique not null,
  start_time timestamptz not null,
  duration_s integer not null,
  avg_hr numeric,
  avg_speed_flat numeric,
  raw_payload jsonb,
  created_at timestamptz default now()
);

create table if not exists workout_zone_stats (
  id bigserial primary key,
  activity_id bigint references workouts(activity_id) on delete cascade,
  zone_type text not null check (zone_type in ('hr','speed')),
  zone_label text not null,
  time_s integer not null,
  mean_hr numeric,
  mean_speed_flat numeric
);

create index if not exists idx_zone_activity on workout_zone_stats(activity_id);
create index if not exists idx_zone_typelabel on workout_zone_stats(zone_type, zone_label);

create table if not exists hr_speed_points (
  id bigserial primary key,
  athlete_id bigint not null,
  activity_id bigint references workouts(activity_id) on delete cascade,
  point_time timestamptz not null,
  hr numeric,
  speed_flat numeric
);

create index if not exists idx_hr_speed_ath_time on hr_speed_points(athlete_id, point_time);

create table if not exists acwr_zone_daily (
  id bigserial primary key,
  athlete_id bigint not null,
  day date not null,
  zone_type text not null check (zone_type in ('hr','speed')),
  zone_label text not null,
  acute_load numeric,
  chronic_load numeric,
  ratio numeric
);

create unique index if not exists uniq_acwr_day on acwr_zone_daily(athlete_id, day, zone_type, zone_label);

create table if not exists model_snapshots (
  id bigserial primary key,
  athlete_id bigint not null,
  created_at timestamptz default now(),
  model_json jsonb
);
