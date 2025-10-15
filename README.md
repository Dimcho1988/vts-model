# onFlows — Streamlit + Supabase (MVP)

This repository is a ready-to-deploy skeleton that implements the core of your **onFlows** algorithm for running load control and evaluation.

## What you get

- ✅ Strava OAuth (connect button + token exchange) ready for Streamlit Cloud
- ✅ ETL → 30s bins: `v`, `grade`, `v_flat`, HR quality masks
- ✅ Zone classification by %CS and zone aggregates per activity
- ✅ CS/W′ estimation (D = CS·T + W′), baseline VTS, and two modeled variants
- ✅ Supabase schema and simple persistence (params, curves, zone stats, indices)
- ✅ Ideal VTS CSV bundled at `data/ideal_distance_time_speed.csv` (replace with your full file)
- ✅ 4 UI sections: Dashboard, Workloads & Zones, VTS Profiles, Plan & Targets (basic plots)

## Quick deploy (Streamlit Cloud)

1. **Create a new app** and upload this zipped repo or connect to GitHub.
2. In **App Secrets** paste and fill `.streamlit/secrets.toml` values:
   - `supabase.url`, `supabase.anon_key` (and `service_key` if you plan server-side jobs),
   - `strava.client_id`, `strava.client_secret`, `strava.redirect_uri` (exact Streamlit app URL).
3. In **Strava My API Application** add the same **Redirect URI**.
4. In Supabase SQL editor run `supabase_schema.sql` (paste content and execute).
5. (Optional) Upload your full **ideal** CSV to `data/ideal_distance_time_speed.csv`.
6. Set **Python version 3.11**; `requirements.txt` will install dependencies.

## Local run

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Notes

- This MVP focuses on the essentials and clean code structure so you can iterate fast.
- The ETL and modeling follow the rules from your spec (k=6 for `v_flat`, 30s bins, guards and caps).
- Extend `utils/vts.py` to add the full warp/tilt logic and HR/V index when you’re ready.
