# onFlows – VTS & Training Control (Phase 4: Weekly Zone Optimum + Fitness Index)

**What’s included**
- VTS: CS & W′, zones, personal curve (+ inverse helper)
- Grade-equalized v_flat (1 Hz -> 30 s bins)
- HR–V regression, FI, and scatter
- Weekly aggregates & ACWR (v_flat-aware)
- NEW: Weekly "Zone Optimum" model (I_Z per zone, I_total per week) with heatmap + line
- Strava OAuth, activities import, streams fetch
- Supabase Postgres persistence

**Run**
```bash
pip install -r requirements.txt
streamlit run app.py
```

**Secrets**
```toml
DATABASE_URL = "postgresql://postgres:<URL_ENC_PASSWORD>@db.<ref>.supabase.co:5432/postgres?sslmode=require"
STRAVA_CLIENT_ID = "<id>"
STRAVA_CLIENT_SECRET = "<secret>"
STRAVA_REDIRECT_URI = "https://<your-app>.streamlit.app"
```