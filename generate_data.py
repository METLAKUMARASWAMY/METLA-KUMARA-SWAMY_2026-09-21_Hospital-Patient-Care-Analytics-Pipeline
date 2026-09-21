"""
generate_data.py
Creates realistic SAMPLE hospital data for the 5 source systems.
Real patient data cannot be shared (privacy), so we simulate it.
The data is intentionally a little "dirty" (nulls, duplicates, wrong formats,
sensor errors) so the Transform step has real cleaning work to do.

Run once before the pipeline:  python generate_data.py
"""
import os
import json
import numpy as np
import pandas as pd
from config import (RAW_DIR, SOURCE_FILES, SCHEDULE_DATE, EMERGENCY_BUFFER_SLOT,
                    NO_SHOW_RISK_THRESHOLD)

rng = np.random.default_rng(42)          # fixed seed -> same data every run
N_PATIENTS = 200
N_APPOINTMENTS = 1200
START = pd.Timestamp("2026-08-01")

FIRST = ["Ravi", "Sita", "Kiran", "Lakshmi", "Suresh", "Anitha", "Rahul", "Priya", "Venkat",
         "Divya", "Srinivas", "Kavya", "Arjun", "Meena", "Mahesh", "Swathi", "Naveen", "Bhavya"]
LAST = ["Kumar", "Reddy", "Rao", "Naidu", "Sharma", "Chowdary", "Varma", "Prasad", "Goud", "Shetty"]
CITIES = ["Markapur", "Ongole", "Guntur", "Vijayawada", "Nellore", "Kurnool", "Hyderabad"]
DEPARTMENTS = {  # department: list of doctor ids
    "Cardiology": ["D01", "D02"], "General Medicine": ["D03", "D04", "D05"],
    "Orthopedics": ["D06", "D07"], "Pediatrics": ["D08"],
    "Neurology": ["D09"], "Pulmonology": ["D10"],
}
CHRONIC = ["None", "Diabetes", "Hypertension", "Heart Disease", "Asthma", "Kidney Disease"]


def make_patients():
    ids = [f"P{i:04d}" for i in range(1, N_PATIENTS + 1)]
    ages = rng.integers(2, 90, N_PATIENTS)
    dob = [(START - pd.DateOffset(years=int(a)) - pd.Timedelta(days=int(rng.integers(0, 365)))).date()
           for a in ages]
    chronic = [rng.choice(CHRONIC, p=[.45, .15, .15, .1, .08, .07]) if a > 30
               else rng.choice(["None", "Asthma"], p=[.9, .1]) for a in ages]
    df = pd.DataFrame({
        "patient_id": ids,
        "name": [f" {rng.choice(FIRST)} {rng.choice(LAST)} " for _ in ids],   # extra spaces on purpose
        "gender": rng.choice(["M", "Male", "male", "F", "Female", "female"], N_PATIENTS),
        "date_of_birth": dob,
        "city": rng.choice(CITIES, N_PATIENTS),
        "blood_group": rng.choice(["A+", "B+", "O+", "AB+", "A-", "O-"], N_PATIENTS),
        "chronic_condition": chronic,
        "registration_date": [(START - pd.Timedelta(days=int(d))).date()
                              for d in rng.integers(0, 700, N_PATIENTS)],
    })
    df.loc[rng.choice(N_PATIENTS, 12, replace=False), "blood_group"] = None
    df.loc[rng.choice(N_PATIENTS, 8, replace=False), "city"] = None
    df.loc[df["chronic_condition"] == "None", "chronic_condition"] = None   # stored as blank in source
    df = pd.concat([df, df.sample(6, random_state=1)])                      # duplicate registrations
    df.to_csv(SOURCE_FILES["patients"], index=False)
    return df.drop_duplicates("patient_id")


def make_appointments(patients):
    rows = []
    for i in range(1, N_APPOINTMENTS + 1):
        dept = rng.choice(list(DEPARTMENTS))
        doctor = rng.choice(DEPARTMENTS[dept])
        day = START + pd.Timedelta(days=int(rng.integers(0, 45)))
        hour = int(rng.choice([9, 10, 11, 12, 13, 14, 15, 16], p=[.12, .2, .2, .15, .08, .1, .08, .07]))
        scheduled = day + pd.Timedelta(hours=hour, minutes=int(rng.choice([0, 15, 30, 45])))
        status = rng.choice(["Completed", "No-Show", "Cancelled"], p=[.82, .12, .06])
        checkin = consult = None
        if status == "Completed":
            checkin = scheduled + pd.Timedelta(minutes=int(rng.integers(-15, 10)))
            base = {"Cardiology": 35, "General Medicine": 45, "Orthopedics": 30,
                    "Pediatrics": 20, "Neurology": 25, "Pulmonology": 25}[dept]
            peak = 20 if hour in (10, 11) else 0                   # morning rush
            wait = max(2, int(rng.normal(base + peak, 12)))
            consult = checkin + pd.Timedelta(minutes=wait)
        rows.append([f"A{i:05d}", rng.choice(patients["patient_id"]), doctor, dept,
                     scheduled, checkin, consult, status])
    df = pd.DataFrame(rows, columns=["appointment_id", "patient_id", "doctor_id", "department",
                                     "scheduled_time", "checkin_time", "consultation_start_time",
                                     "status"])
    # data-entry errors: consultation recorded before check-in
    bad = df[df["status"] == "Completed"].sample(8, random_state=3).index
    df.loc[bad, "consultation_start_time"] = df.loc[bad, "checkin_time"] - pd.Timedelta(minutes=30)
    # a few appointments for patient ids that don't exist
    df.loc[rng.choice(len(df), 5, replace=False), "patient_id"] = "P9999"
    df.to_csv(SOURCE_FILES["appointments"], index=False)
    return df


def make_lab_reports(patients):
    normal = {"Hemoglobin": (14, 1.5, "g/dL"), "Fasting Blood Sugar": (90, 8, "mg/dL"),
              "Total Cholesterol": (175, 20, "mg/dL"), "Creatinine": (0.95, 0.15, "mg/dL"),
              "WBC Count": (7.5, 1.5, "10^3/uL")}
    shift = {"Diabetes": {"Fasting Blood Sugar": 60}, "Heart Disease": {"Total Cholesterol": 60},
             "Hypertension": {"Total Cholesterol": 35}, "Kidney Disease": {"Creatinine": 1.2}}
    reports, rid = [], 1
    for _, p in patients.iterrows():
        cond = p["chronic_condition"] if isinstance(p["chronic_condition"], str) else "None"
        for test, (mu, sd, unit) in normal.items():
            if rng.random() < 0.3:
                continue
            val = rng.normal(mu + shift.get(cond, {}).get(test, 0), sd)
            value = round(float(val), 2)
            if rng.random() < 0.03:
                value = None                    # missing result
            elif rng.random() < 0.15:
                value = str(value)              # numbers stored as text in some records
            reports.append({"report_id": f"L{rid:05d}", "patient_id": p["patient_id"],
                            "test_name": test, "result_value": value, "unit": unit,
                            "report_date": str((START + pd.Timedelta(days=int(rng.integers(0, 45)))).date())})
            rid += 1
    with open(SOURCE_FILES["lab_reports"], "w") as f:
        json.dump({"source": "hospital_lab_system", "reports": reports}, f, indent=2)


def make_wearables(patients):
    monitored = patients.sample(60, random_state=7)          # only 60 patients wear devices
    rows = []
    for _, p in monitored.iterrows():
        sick = isinstance(p["chronic_condition"], str) and p["chronic_condition"] in (
            "Heart Disease", "Hypertension", "Asthma")
        for h in range(72):                                   # 3 days, hourly readings
            ts = START + pd.Timedelta(days=30, hours=h)
            hr = rng.normal(95 if sick else 76, 14 if sick else 8)
            spo2 = rng.normal(93 if sick else 97.5, 2.2 if sick else 1)
            temp = rng.normal(37.1 if sick else 36.7, 0.5 if sick else 0.3)
            rows.append([p["patient_id"], f"W-{p['patient_id']}", ts,
                         round(hr), round(min(spo2, 100), 1), round(temp, 1)])
    df = pd.DataFrame(rows, columns=["patient_id", "device_id", "reading_time",
                                     "heart_rate", "spo2", "body_temp"])
    err = rng.choice(len(df), 60, replace=False)             # sensor glitches
    df.loc[err[:20], "heart_rate"] = 0
    df.loc[err[20:35], "heart_rate"] = 300
    df.loc[err[35:50], "spo2"] = None
    df.loc[err[50:], "body_temp"] = 0.0
    df = pd.concat([df, df.sample(40, random_state=2)])      # duplicate transmissions
    df.to_csv(SOURCE_FILES["wearables"], index=False)


def make_notes(patients):
    templates = [
        "Patient complains of {s1} and {s2}. Advised rest and follow-up.",
        "Presented with {s1} since 3 days. {S2} also reported. Prescribed medication.",
        "Routine check-up. Mild {s1}. No other complaints.",
        "Patient reports {s1}, {s2}. Referred for further tests.",
    ]
    common = ["fever", "cough", "headache", "fatigue", "joint pain", "dizziness", "swelling"]
    critical = ["chest pain", "shortness of breath", "palpitations"]
    rows = []
    for i in range(1, 451):
        p = patients.sample(1, random_state=int(rng.integers(0, 1e6))).iloc[0]
        heart = isinstance(p["chronic_condition"], str) and p["chronic_condition"] in (
            "Heart Disease", "Hypertension")
        pool = critical + common[:2] if heart else common
        s1, s2 = rng.choice(pool, 2, replace=False)
        text = rng.choice(templates).format(s1=s1, s2=s2, S2=s2.capitalize())
        rows.append([f"N{i:04d}", p["patient_id"], rng.choice(sum(DEPARTMENTS.values(), [])),
                     str((START + pd.Timedelta(days=int(rng.integers(0, 45)))).date()),
                     text.upper() if rng.random() < 0.1 else text])  # some notes typed in caps
    pd.DataFrame(rows, columns=["note_id", "patient_id", "doctor_id", "visit_date", "note_text"]) \
        .to_csv(SOURCE_FILES["doctor_notes"], index=False)


def make_upcoming_schedule(patients, appointments):
    """
    Tomorrow's booked schedule from the scheduling system (future appointments).
    Each doctor has 14 slots of 30 min; the 10:30 slot is an EMERGENCY BUFFER slot.
    Some doctors are fully booked on purpose, to demonstrate emergency prioritisation.
    """
    # booking history of each patient -> who usually comes, who often doesn't
    hist = appointments.groupby("patient_id")["status"].agg(
        visits="count", no_shows=lambda s: (s == "No-Show").sum())
    hist["rate"] = hist["no_shows"] / hist["visits"]
    reliable = list(hist[(hist["visits"] >= 3) & (hist["no_shows"] == 0)].index)
    prone = list(hist[(hist["visits"] >= 3) & (hist["rate"] >= NO_SHOW_RISK_THRESHOLD)].index)
    others = [p for p in patients["patient_id"] if p not in prone and p not in reliable]
    rng.shuffle(reliable); rng.shuffle(others)

    times = ["09:00", "09:30", "10:00", EMERGENCY_BUFFER_SLOT, "11:00", "11:30", "12:00",
             "12:30", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30"]
    regular = [t for t in times if t != EMERGENCY_BUFFER_SLOT]
    #          doctor: (regular slots booked, buffer already used?, patient pool, triage of bookings)
    plan = {"D01": (13, True, "reliable", 4),   # Cardiology  - full (one no-show-prone patient)
            "D02": (13, True, "reliable", 2),   # Cardiology  - full with urgent follow-ups
            "D03": (11, False, "others", 4),    # Gen Med     - buffer free
            "D04": (10, False, "others", 4),
            "D05": (12, False, "others", 4),
            "D06": (13, True, "reliable", 4),   # Orthopedics - full
            "D07": (11, False, "others", 4),    # Orthopedics - has free slots
            "D08": (12, False, "others", 4),    # Pediatrics
            "D09": (13, True, "reliable", 4),   # Neurology   - full, only doctor
            "D10": (9, False, "others", 4)}     # Pulmonology
    dept_of = {d: dep for dep, docs in DEPARTMENTS.items() for d in docs}
    pools = {"reliable": reliable, "others": others}
    rows, sid = [], 1
    for doc, (n_regular, buffer_used, pool, triage) in plan.items():
        booked_times = set(rng.choice(regular, n_regular, replace=False))
        if buffer_used:
            booked_times.add(EMERGENCY_BUFFER_SLOT)
        for t in times:
            pid = pools[pool].pop() if t in booked_times else None
            if doc == "D01" and t == "14:30":
                pid = prone[0]                  # a patient who often skips appointments
            rows.append([f"S{sid:04d}", doc, dept_of[doc], f"{SCHEDULE_DATE} {t}:00",
                         "buffer" if t == EMERGENCY_BUFFER_SLOT else "regular",
                         pid, triage if pid else None])
            sid += 1
    pd.DataFrame(rows, columns=["slot_id", "doctor_id", "department", "slot_time", "slot_type",
                                "patient_id", "triage_level"]) \
        .to_csv(SOURCE_FILES["upcoming_schedule"], index=False)


if __name__ == "__main__":
    os.makedirs(RAW_DIR, exist_ok=True)
    pats = make_patients()
    appts = make_appointments(pats)
    make_lab_reports(pats)
    make_wearables(pats)
    make_notes(pats)
    make_upcoming_schedule(pats, appts)
    print(f"Sample source data created in: {RAW_DIR}")
    for name, path in SOURCE_FILES.items():
        print(f"  - {name:<17} -> {os.path.basename(path)}")
