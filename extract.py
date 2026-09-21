"""
extract.py  -  E of ETL
Reads raw data from the 5 hospital source systems.
Each source has a different format, so each has its own reader.
"""
import json
import logging
import pandas as pd
from config import SOURCE_FILES

logger = logging.getLogger(__name__)


def extract_patients():
    """Patient registration system -> CSV (structured)."""
    return pd.read_csv(SOURCE_FILES["patients"])


def extract_appointments():
    """Appointment scheduling system -> CSV (structured, transactional)."""
    return pd.read_csv(SOURCE_FILES["appointments"])


def extract_lab_reports():
    """Laboratory system -> nested JSON (semi-structured)."""
    with open(SOURCE_FILES["lab_reports"]) as f:
        data = json.load(f)
    return pd.json_normalize(data["reports"])      # flatten JSON into a table


def extract_wearables():
    """Wearable devices -> time-series readings (CSV export of device feed)."""
    return pd.read_csv(SOURCE_FILES["wearables"])


def extract_doctor_notes():
    """Consultation notes -> free text (unstructured)."""
    return pd.read_csv(SOURCE_FILES["doctor_notes"])


def extract_upcoming_schedule():
    """Scheduling system -> tomorrow's booked slots (CSV, used for emergency scheduling)."""
    return pd.read_csv(SOURCE_FILES["upcoming_schedule"])


def extract():
    """Run all extractors and return a dictionary of raw DataFrames."""
    raw = {
        "patients": extract_patients(),
        "appointments": extract_appointments(),
        "lab_reports": extract_lab_reports(),
        "wearables": extract_wearables(),
        "doctor_notes": extract_doctor_notes(),
        "upcoming_schedule": extract_upcoming_schedule(),
    }
    for name, df in raw.items():
        logger.info(f"Extracted {name:<17}: {len(df):>5} rows, {len(df.columns)} columns")
    return raw
