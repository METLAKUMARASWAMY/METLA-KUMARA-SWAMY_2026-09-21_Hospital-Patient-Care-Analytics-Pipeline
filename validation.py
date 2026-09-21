"""
validation.py
Data quality checks run AFTER transform and BEFORE load.
If any check fails, the pipeline stops, so bad data never reaches the database.
"""
import logging
from config import VALID_VITAL_RANGES

logger = logging.getLogger(__name__)


def validate_patients(df):
    assert df["patient_id"].is_unique, "Duplicate patient_id found"
    assert df.isnull().sum().sum() == 0, "Patients table contains null values"
    assert df["gender"].isin(["Male", "Female"]).all(), "Gender has invalid values"
    assert df["age"].between(0, 120).all(), "Age out of range"


def validate_appointments(df, patient_ids):
    assert df["appointment_id"].is_unique, "Duplicate appointment_id found"
    assert df["patient_id"].isin(patient_ids).all(), "Appointment for unknown patient"
    assert df["status"].isin(["Completed", "No-Show", "Cancelled"]).all(), "Invalid status"
    completed = df[df["status"] == "Completed"]
    assert completed["waiting_minutes"].notna().all(), "Completed visit without waiting time"
    assert (completed["waiting_minutes"] >= 0).all(), "Negative waiting time found"


def validate_lab_results(df):
    assert df["result_value"].notna().all(), "Lab result missing"
    assert df["result_status"].isin(["Low", "Normal", "High"]).all(), "Invalid lab status"


def validate_vitals(df):
    for col, (low, high) in VALID_VITAL_RANGES.items():
        assert df[col].between(low, high).all(), f"{col} has impossible values"
    assert not df.duplicated(["device_id", "reading_time"]).any(), "Duplicate wearable readings"


def validate_doctor_notes(df):
    assert df["note_text"].notna().all(), "Empty doctor note found"


def validate_patient_risk(df, patient_ids):
    assert len(df) == len(patient_ids), "Risk table must have one row per patient"
    assert df["risk_level"].isin(["Low", "Medium", "High"]).all(), "Invalid risk level"


def validate_upcoming_appointments(df, patient_ids):
    assert not df.duplicated(["doctor_id", "slot_time"]).any(), "Doctor double-booked in schedule"
    assert df["slot_type"].isin(["regular", "buffer"]).all(), "Invalid slot type"
    booked = df[df["slot_status"] == "Booked"]
    assert booked["patient_id"].isin(patient_ids).all(), "Booked slot has unknown patient"
    assert booked["triage_level"].between(1, 4).all(), "Invalid triage level"
    assert df.loc[df["slot_status"] == "Free", "patient_id"].isna().all(), "Free slot has a patient"


def validate(clean):
    patient_ids = set(clean["patients"]["patient_id"])
    validate_patients(clean["patients"])
    validate_appointments(clean["appointments"], patient_ids)
    validate_lab_results(clean["lab_results"])
    validate_vitals(clean["vitals"])
    validate_doctor_notes(clean["doctor_notes"])
    validate_patient_risk(clean["patient_risk_scores"], patient_ids)
    validate_upcoming_appointments(clean["upcoming_appointments"], patient_ids)
    logger.info("Validation Passed - all data quality checks OK")
