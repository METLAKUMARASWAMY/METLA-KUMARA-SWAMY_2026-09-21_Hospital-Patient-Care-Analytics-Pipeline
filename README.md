# Hospital Patient Care Analytics – ETL Pipeline

End-to-end ETL pipeline that collects data from 5 hospital systems, cleans it,
validates it, loads it into MySQL, and answers three business goals:
**reduce waiting times, improve patient care, and identify high-risk patients.**

## Workflow
```
Sources (CSV / JSON / text) -> Extract -> Transform -> Validate -> Load (MySQL) -> Analyse + Dashboards + Emergency scheduler
```
See `docs/workflow_diagram.png`.

## Project structure
| File | Purpose |
|---|---|
| `config.py` | DB settings, file paths, business rules (thresholds, ranges) |
| `generate_data.py` | Creates sample raw data for the 5 source systems |
| `extract.py` | **E** – reads CSV, JSON and text sources |
| `transform.py` | **T** – cleaning, new columns, patient risk score |
| `validation.py` | Data quality checks (pipeline stops if any fail) |
| `load.py` | **L** – loads 6 tables into MySQL + CSV backup |
| `pipeline.py` | Runs all steps in order with logging |
| `analysis.py` + `sql/analysis_queries.sql` | Business queries |
| `visualize.py` | Dashboard charts saved in `reports/` |
| `emergency_scheduler.py` | Finds and books a slot for an emergency patient when the doctor is fully booked |
| `app.py` | Clickable web app: dashboard, emergency booking, doctor schedule, bookings log, run pipeline |

## How to run
```bash
pip install -r requirements.txt

# set your MySQL password (never hard-code it)
export DB_PASSWORD='your_mysql_password'      # Mac / Linux
# set DB_PASSWORD=your_mysql_password         # Windows CMD

python generate_data.py   # 1. create raw source data (run once)
python pipeline.py        # 2. run ETL + print insights
python visualize.py       # 3. create dashboard charts
python emergency_scheduler.py   # 4. emergency prioritisation demo (6 scenarios)
streamlit run app.py            # 5. open the clickable web app in the browser
```

### Emergency booking from the terminal
```bash
python emergency_scheduler.py --patient P0098 --doctor D01 --triage 2          # suggestion only
python emergency_scheduler.py --patient P0098 --doctor D01 --triage 2 --book   # save booking
python emergency_scheduler.py --reset                                          # undo all bookings
```

### Web app (`streamlit run app.py`)
Opens http://localhost:8501 with five pages:
- **Dashboard** – key numbers and charts
- **Emergency Booking** – choose patient, doctor, triage → *Find best slot* → *Confirm booking*
- **Doctor Schedule** – colour-coded grid of tomorrow's slots (updates after each booking)
- **Bookings Log** – every emergency booking + *Reset schedule* button
- **Run Pipeline** – generate data and run the ETL with one click
The `hospital_db` database is created automatically.
No MySQL? Test with SQLite: `USE_SQLITE=1 python pipeline.py`

## Output tables (MySQL: hospital_db)
`patients`, `appointments`, `lab_results`, `vitals`, `doctor_notes`, `patient_risk_scores`, `upcoming_appointments`, plus `emergency_bookings` (created when a booking is saved)

## Emergency prioritisation
`priority = (5 - triage_level) x 10 + risk_score`. When the doctor is full, the scheduler tries, in order:
0. Triage 1 (life-threatening) -> Emergency Department immediately
1. Free emergency buffer slot (10:30, peak hour)
2. Double-book a slot of a patient likely to not show up (>= 40% no-show history)
3. Free slot with another doctor in the same department
4. Reschedule the lowest-priority booked patient
5. Overbook an extra slot at 17:00 (last resort)
# METLA-KUMARA-SWAMY_2026-09-21_Hospital-Patient-Care-Analytics-Pipeline
