"""
transform.py  -  T of ETL
Cleans each raw table and creates new, useful columns.
Finally combines everything into one 'patient_risk_scores' table.
"""
import logging
import pandas as pd
from config import (LAB_REFERENCE_RANGES, VALID_VITAL_RANGES, ABNORMAL_VITALS,
                    SYMPTOM_KEYWORDS, CRITICAL_SYMPTOMS, RISK_LEVELS)

logger = logging.getLogger(__name__)
TODAY = pd.Timestamp("2026-09-21")


# ------------------------------------------------------------------ patients
def transform_patients(df):
    df = df.copy()
    before = len(df)
    df = df.drop_duplicates(subset="patient_id")                  # remove duplicate registrations
    df["name"] = df["name"].str.strip().str.title()               # " ravi kumar " -> "Ravi Kumar"
    df["gender"] = (df["gender"].str.strip().str.lower()
                    .map({"m": "Male", "male": "Male", "f": "Female", "female": "Female"}))
    df["date_of_birth"] = pd.to_datetime(df["date_of_birth"])
    df["registration_date"] = pd.to_datetime(df["registration_date"])
    df["age"] = ((TODAY - df["date_of_birth"]).dt.days // 365).astype(int)
    df["age_group"] = pd.cut(df["age"], bins=[0, 12, 25, 45, 60, 120],
                             labels=["Child", "Young Adult", "Adult", "Middle Aged", "Senior"]).astype(str)
    df["city"] = df["city"].fillna("Unknown")
    df["blood_group"] = df["blood_group"].fillna("Unknown")
    df["chronic_condition"] = df["chronic_condition"].fillna("None")
    logger.info(f"patients     : removed {before - len(df)} duplicates")
    return df


# -------------------------------------------------------------- appointments
def transform_appointments(df, valid_patients):
    df = df.copy()
    before = len(df)
    for col in ["scheduled_time", "checkin_time", "consultation_start_time"]:
        df[col] = pd.to_datetime(df[col])

    df = df[df["patient_id"].isin(valid_patients)]                # referential integrity
    orphan = before - len(df)

    # waiting time = consultation start - check-in (only for completed visits)
    df["waiting_minutes"] = (df["consultation_start_time"] - df["checkin_time"]).dt.total_seconds() / 60
    invalid = (df["status"] == "Completed") & (df["waiting_minutes"] < 0)
    df = df[~invalid]                                             # data-entry errors

    df["appointment_date"] = df["scheduled_time"].dt.date
    df["appointment_hour"] = df["scheduled_time"].dt.hour
    df["day_of_week"] = df["scheduled_time"].dt.day_name()
    df["is_no_show"] = (df["status"] == "No-Show").astype(int)
    logger.info(f"appointments : removed {orphan} unknown-patient rows, {invalid.sum()} invalid times")
    return df


# ---------------------------------------------------------------------- labs
def transform_lab_reports(df, valid_patients):
    df = df.copy()
    before = len(df)
    df["result_value"] = pd.to_numeric(df["result_value"], errors="coerce")   # "126.5" -> 126.5
    df = df.dropna(subset=["result_value"])
    df = df[df["patient_id"].isin(valid_patients)]
    df["report_date"] = pd.to_datetime(df["report_date"])

    df["ref_low"] = df["test_name"].map(lambda t: LAB_REFERENCE_RANGES[t][0])
    df["ref_high"] = df["test_name"].map(lambda t: LAB_REFERENCE_RANGES[t][1])
    df["result_status"] = "Normal"
    df.loc[df["result_value"] < df["ref_low"], "result_status"] = "Low"
    df.loc[df["result_value"] > df["ref_high"], "result_status"] = "High"
    df["is_abnormal"] = (df["result_status"] != "Normal").astype(int)
    logger.info(f"lab_reports  : removed {before - len(df)} rows with missing/invalid results")
    return df


# ----------------------------------------------------------------- wearables
def transform_wearables(df):
    df = df.copy()
    before = len(df)
    df["reading_time"] = pd.to_datetime(df["reading_time"])
    df = df.drop_duplicates(subset=["device_id", "reading_time"])  # repeated transmissions
    dups = before - len(df)

    # remove physically impossible readings (sensor errors)
    valid = pd.Series(True, index=df.index)
    for col, (low, high) in VALID_VITAL_RANGES.items():
        valid &= df[col].between(low, high)                        # NaN -> False
    df = df[valid]

    t = ABNORMAL_VITALS
    df["is_abnormal_vital"] = ((df["heart_rate"] > t["heart_rate_high"]) |
                               (df["heart_rate"] < t["heart_rate_low"]) |
                               (df["spo2"] < t["spo2_low"]) |
                               (df["body_temp"] > t["body_temp_high"])).astype(int)
    logger.info(f"wearables    : removed {dups} duplicates, {(~valid).sum()} sensor errors")
    return df


# -------------------------------------------------------------- doctor notes
def transform_doctor_notes(df):
    df = df.copy()
    df["note_text"] = df["note_text"].str.strip().str.lower()     # normalise text
    df["visit_date"] = pd.to_datetime(df["visit_date"])
    df["symptoms_found"] = df["note_text"].apply(
        lambda txt: ", ".join(k for k in SYMPTOM_KEYWORDS if k in txt) or "none")
    df["has_critical_symptom"] = df["note_text"].apply(
        lambda txt: int(any(k in txt for k in CRITICAL_SYMPTOMS)))
    logger.info(f"doctor_notes : {df['has_critical_symptom'].sum()} notes mention critical symptoms")
    return df


# --------------------------------------------------------- upcoming schedule
def transform_upcoming_schedule(df, valid_patients):
    df = df.copy()
    df["slot_time"] = pd.to_datetime(df["slot_time"])
    df["slot_status"] = df["patient_id"].notna().map({True: "Booked", False: "Free"})
    df["triage_level"] = df["triage_level"].astype("Int64")        # 4.0 -> 4, blank stays empty
    unknown = df["patient_id"].notna() & ~df["patient_id"].isin(valid_patients)
    df.loc[unknown, ["patient_id", "triage_level"]] = None           # invalid booking -> free slot
    df.loc[unknown, "slot_status"] = "Free"
    booked = (df["slot_status"] == "Booked").sum()
    logger.info(f"schedule     : {booked} of {len(df)} slots booked for {df['slot_time'].dt.date.iloc[0]}")
    return df


# -------------------------------------------------------- patient risk table
def build_patient_risk(patients, appointments, labs, vitals, notes):
    """Combine all sources into one row per patient with a rule-based risk score."""
    lab_agg = labs.groupby("patient_id")["is_abnormal"].sum().rename("abnormal_lab_count")
    vit_agg = vitals.groupby("patient_id").agg(
        avg_heart_rate=("heart_rate", "mean"), min_spo2=("spo2", "min"),
        abnormal_vital_pct=("is_abnormal_vital", "mean"))
    note_agg = notes.groupby("patient_id")["has_critical_symptom"].sum().rename("critical_symptom_notes")
    appt_agg = appointments.groupby("patient_id").agg(
        total_visits=("appointment_id", "count"), no_shows=("is_no_show", "sum"))

    risk = (patients[["patient_id", "name", "age", "gender", "chronic_condition"]]
            .set_index("patient_id")
            .join([appt_agg, lab_agg, vit_agg, note_agg]))
    count_cols = ["total_visits", "no_shows", "abnormal_lab_count", "critical_symptom_notes"]
    risk[count_cols] = risk[count_cols].fillna(0).astype(int)
    risk["has_wearable"] = risk["avg_heart_rate"].notna().astype(int)
    risk[["avg_heart_rate", "min_spo2", "abnormal_vital_pct"]] = \
        risk[["avg_heart_rate", "min_spo2", "abnormal_vital_pct"]].fillna(0).round(2)

    # ---- rule-based risk score (each factor adds points) ----
    score = pd.Series(0, index=risk.index)
    score += (risk["age"] >= 60) * 2
    score += (risk["chronic_condition"] != "None") * 2
    score += risk["abnormal_lab_count"].clip(upper=3)
    score += (risk["abnormal_vital_pct"] > 0.30) * 2
    score += risk["critical_symptom_notes"].clip(upper=2)
    risk["risk_score"] = score.astype(int)

    def level(s):
        for low, high, name in RISK_LEVELS:
            if low <= s <= high:
                return name
    risk["risk_level"] = risk["risk_score"].apply(level)
    logger.info(f"patient_risk : {risk['risk_level'].value_counts().to_dict()}")
    return risk.reset_index()


def transform(raw):
    """Run all transformations and return a dictionary of clean DataFrames."""
    patients = transform_patients(raw["patients"])
    valid_ids = set(patients["patient_id"])
    appointments = transform_appointments(raw["appointments"], valid_ids)
    labs = transform_lab_reports(raw["lab_reports"], valid_ids)
    vitals = transform_wearables(raw["wearables"])
    notes = transform_doctor_notes(raw["doctor_notes"])
    schedule = transform_upcoming_schedule(raw["upcoming_schedule"], valid_ids)
    risk = build_patient_risk(patients, appointments, labs, vitals, notes)
    return {
        "patients": patients,
        "appointments": appointments,
        "lab_results": labs,
        "vitals": vitals,
        "doctor_notes": notes,
        "patient_risk_scores": risk,
        "upcoming_appointments": schedule,
    }
