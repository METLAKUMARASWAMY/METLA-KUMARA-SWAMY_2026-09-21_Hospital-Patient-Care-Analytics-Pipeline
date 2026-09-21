"""
config.py
Central place for all settings used by the pipeline.
The database password is read from an environment variable so it is never
written inside the code (safe to submit / push to GitHub).
"""
import os

# ---------------- Database settings ----------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),   # set with: export DB_PASSWORD='your_password'
    "database": os.getenv("DB_NAME", "hospital_db"),
}

# Set USE_SQLITE=1 to test the pipeline without MySQL (creates hospital.db file)
USE_SQLITE = os.getenv("USE_SQLITE", "0") == "1"

# ---------------- File paths ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
LOG_DIR = os.path.join(BASE_DIR, "logs")

SOURCE_FILES = {
    "patients": os.path.join(RAW_DIR, "patients.csv"),          # Registration system
    "appointments": os.path.join(RAW_DIR, "appointments.csv"),  # Scheduling system
    "lab_reports": os.path.join(RAW_DIR, "lab_reports.json"),   # Laboratory system
    "wearables": os.path.join(RAW_DIR, "wearables.csv"),        # Wearable devices
    "doctor_notes": os.path.join(RAW_DIR, "doctor_notes.csv"),  # Consultation notes
    "upcoming_schedule": os.path.join(RAW_DIR, "upcoming_schedule.csv"),  # Tomorrow's bookings
}

# ---------------- Business rules ----------------
# Normal reference ranges for lab tests: (low, high)
LAB_REFERENCE_RANGES = {
    "Hemoglobin": (12.0, 17.5),
    "Fasting Blood Sugar": (70, 100),
    "Total Cholesterol": (0, 200),
    "Creatinine": (0.6, 1.3),
    "WBC Count": (4.0, 11.0),
}

# Physically possible ranges for wearable readings (outside = sensor error)
VALID_VITAL_RANGES = {
    "heart_rate": (30, 220),
    "spo2": (50, 100),
    "body_temp": (34.0, 43.0),
}

# Clinical thresholds for an abnormal (but real) reading
ABNORMAL_VITALS = {
    "heart_rate_high": 100,
    "heart_rate_low": 50,
    "spo2_low": 92,
    "body_temp_high": 38.0,
}

# Symptoms searched for in doctor notes (critical ones add to risk)
SYMPTOM_KEYWORDS = [
    "chest pain", "shortness of breath", "dizziness", "fever", "fatigue",
    "headache", "cough", "palpitations", "swelling", "joint pain",
]
CRITICAL_SYMPTOMS = ["chest pain", "shortness of breath", "palpitations"]

# Risk score -> risk level
RISK_LEVELS = [(0, 3, "Low"), (4, 6, "Medium"), (7, 100, "High")]

# ---------------- Emergency scheduling rules ----------------
SCHEDULE_DATE = "2026-09-22"          # date of the upcoming schedule (tomorrow)
EMERGENCY_BUFFER_SLOT = "10:30"       # one slot per doctor kept free for emergencies (peak hour)
NO_SHOW_RISK_THRESHOLD = 0.4          # patient misses >= 40% of appointments -> likely no-show
MIN_VISITS_FOR_NO_SHOW = 3            # need at least 3 past visits to judge
OVERBOOK_TIME = "17:00"               # extra slot added at end of day as last resort
# Triage levels: 1 = Immediate (life-threatening), 2 = Very urgent, 3 = Urgent, 4 = Routine
TRIAGE_LABELS = {1: "Immediate", 2: "Very urgent", 3: "Urgent", 4: "Routine"}
