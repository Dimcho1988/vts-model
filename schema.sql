create table if not exists user_profiles (
  athlete_id       bigint primary key,
  display_name     text,
  email            text,
  hrmax            integer,
  cs_kmh           numeric,
  speed_zone_perc  jsonb,
  speed_zone_abs   jsonb,
  updated_at       timestamptz default now()
);
create table if not exists workouts (
  id              bigserial primary key,
  athlete_id      bigint not null,
  activity_id     bigint unique,
  start_time      timestamptz not null,
  duration_s      integer,
  avg_hr          numeric,
  avg_speed_flat  numeric,
  raw_payload     jsonb
);
create table if not exists hr_speed_points (
  id              bigserial primary key,
  athlete_id      bigint not null,
  activity_id     bigint not null,
  point_time      timestamptz not null,
  hr              numeric,
  speed_flat      numeric
);
create index if not exists idx_hrsp_ath_time on hr_speed_points(athlete_id, point_time);
create table if not exists zone_stats (
  id              bigserial primary key,
  activity_id     bigint not null,
  athlete_id      bigint not null,
  zone_type       text not null,
  zone_label      text not null,
  time_s          integer,
  mean_hr         numeric,
  mean_speed_flat numeric,
  distance_m      numeric
);
