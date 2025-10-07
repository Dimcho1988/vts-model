
Strava Add-on (Drop‑in) for your existing Streamlit app
=======================================================

What you get
------------
• OAuth helper for Strava (optional simple token mode as fallback)
• Strava API client (activities + streams)
• Processing pipeline:
    - 30s binning with averaged values
    - Elevation/grade-adjusted "flat-equivalent" speed
    - Zoning by HR and Speed
• ACWR by zone (7d acute / 28d chronic) using zone-load = mean_speed_in_zone * time_in_zone
• Dynamic V=f(HR) model (rolling / exponential-weighted fit)
• Streamlit UI module that plugs into your current app (single import + one function call)
• SQL schema for Postgres (Supabase) for storing results

Minimal edits to your existing app
----------------------------------
1) Add to requirements.txt (or environment):
   pandas
   numpy
   requests
   SQLAlchemy
   psycopg2-binary
   scikit-learn
   plotly

2) Drop the files from this ZIP into your repo root (no folder moves needed).
   Keep your current structure. New files are self-contained.

3) In your existing `streamlit_app.py` (or main module), add:
   ----------------------------------------------------------
   # NEW imports
   from ui_strava import render_strava_tab

   # Somewhere in your UI (e.g., in tabs or a sidebar section):
   render_strava_tab()

   That's it. The Strava UI renders inside your current app.

4) Database connection:
   Set an env var DATABASE_URL to your Postgres URL (Supabase):
   Example: postgresql://postgres.USER:YOUR-PASSWORD@HOST:PORT/postgres

   The code will auto-create tables if missing (using SQLAlchemy).

5) Strava auth:
   - Recommended: Create a Strava API app and set env vars:
     STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REDIRECT_URI
     (The redirect URI should be your Streamlit app URL.)
   - Fallback: Paste a temporary Strava access token in the UI for quick tests.

Data model (Postgres)
---------------------
Tables created:
- workouts
    id (PK), athlete_id, activity_id, start_time, duration_s, avg_hr,
    avg_speed_flat, raw_payload (JSONB)
- workout_zone_stats
    id (PK), activity_id (FK), zone_type ('hr'|'speed'), zone_label,
    time_s, mean_hr, mean_speed_flat
- hr_speed_points
    id (PK), athlete_id, activity_id, point_time, hr, speed_flat
- acwr_zone_daily
    id (PK), athlete_id, day (date), zone_type, zone_label,
    acute_load, chronic_load, ratio
- model_snapshots
    id (PK), athlete_id, created_at, model_json

Indices for typical queries are included.

Elevation/grade adjustment
--------------------------
By default we use: speed_flat = speed / (1 + k*grade), with grade as decimal
(e.g., +0.05 for +5%). Coefficients are asymmetric:
  k_up = 0.035 for uphill, k_down = 0.018 for downhill (clamped to [-0.2, +0.2]).
You can tune these in processing.py -> grade_to_flat_speed().

ACWR
----
- Zone load per activity: zone_load = mean_speed_in_zone * time_in_zone_hours
- Acute: rolling 7 days sum; Chronic: rolling 28 days average; Ratio = Acute / Chronic
- Computed per athlete, per zone, per day.

Dynamic V=f(HR)
----------------
- We store (avg HR, avg flat speed) per workout and also per-30s points.
- The model uses exponentially-weighted linear regression with a rolling window
  (configurable). Prediction error per new workout:
    fatigue_index = v_real_flat - v_pred_from_HR
  Interpretation:
    negative -> slower than expected (fatigue); positive -> faster (fitness).

Integrating with Critical Speed (CS)
------------------------------------
- We return the fatigue_index per workout. If you want a "CS_adj" you can do:
    CS_adj = CS + alpha * fatigue_index
  where alpha (e.g., 1.0) is a scaling factor. See models.py -> merge_with_cs().

UI
--
The UI includes:
- Auth & fetch activities
- Process & save to DB
- Per-activity zone table and charts
- ACWR by zone (chart)
- Dynamic V=f(HR) plot and fatigue index timeline

Enjoy! If something isn't wired exactly to your setup, all modules are short and
easy to tweak without moving your existing files.
