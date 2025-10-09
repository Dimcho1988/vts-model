# onFlows – VTS Model App (Streamlit)

Build a personalized Velocity–Time–Speed (VTS) model from an *ideal* curve
(`ideal_distance_time_speed.csv`) and your test points. Computes CS & W′, zones, HR–V regression,
Fatigue Index (FI) and ACWR.

## Run
```
pip install -r requirements.txt
streamlit run app/app.py
```
If `DATABASE_URL` is not set, local SQLite `onflows.db` is used.
