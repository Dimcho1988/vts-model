create table if not exists user_profiles (
  id uuid primary key default gen_random_uuid(),
  athlete_key text unique not null,
  hr_max integer,
  created_at timestamptz default now()
);
create table if not exists workouts (
  id bigserial primary key,
  athlete_key text not null references user_profiles(athlete_key) on delete cascade,
  start_time timestamptz not null,
  duration_s integer not null,
  distance_m numeric not null,
  avg_hr numeric,
  avg_speed_mps numeric,
  notes text
);
create index if not exists idx_workouts_athlete_time on workouts(athlete_key, start_time);

create table if not exists hr_speed_points (
  id bigserial primary key,
  workout_id bigint references workouts(id) on delete cascade,
  t_bin_start timestamptz,
  mean_hr numeric,
  mean_vflat numeric
);
create index if not exists idx_hrv_workout on hr_speed_points(workout_id);

create table if not exists zone_stats (
  id bigserial primary key,
  athlete_key text not null references user_profiles(athlete_key) on delete cascade,
  week_start date not null,
  zone smallint not null,
  time_min numeric not null default 0,
  distance_km numeric not null default 0
);
create index if not exists idx_zone_stats_athlete_week on zone_stats(athlete_key, week_start);

-- Strava tokens per athlete
create table if not exists strava_tokens (
  athlete_key text primary key references user_profiles(athlete_key) on delete cascade,
  strava_athlete_id bigint,
  access_token text,
  refresh_token text,
  expires_at timestamptz
);
create index if not exists idx_tokens_strava_id on strava_tokens(strava_athlete_id);
