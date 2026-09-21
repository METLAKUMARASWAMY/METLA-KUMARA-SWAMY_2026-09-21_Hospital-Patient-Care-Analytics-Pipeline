"""
emergency_scheduler.py
Finds - and books - a slot for an EMERGENCY patient when the doctor's schedule may be full.
Uses data loaded by the ETL pipeline:
    - upcoming_appointments  : tomorrow's booked / free slots
    - patient_risk_scores    : risk score + no-show history of every patient
Bookings are saved back into MySQL and logged in the 'emergency_bookings' table.

Priority score (higher = seen first):
    priority = (5 - triage_level) x 10 + risk_score
    triage 1 Immediate -> 40, 2 Very urgent -> 30, 3 Urgent -> 20, 4 Routine -> 10

Decision steps for triage 1-3 (least disruptive first):
    0. Triage 1 (life-threatening) -> Emergency Department immediately, no appointment
    1. Free EMERGENCY BUFFER slot with the same doctor
    2. Double-book the slot of a patient who is LIKELY TO NOT SHOW UP
    3. Free slot with ANOTHER DOCTOR in the same department
    4. RESCHEDULE the lowest-priority booked patient (only if lower than emergency)
    5. OVERBOOK an extra slot at the end of the day (last resort)
Triage 4 (routine) never disturbs anyone: it gets the next free regular slot, or next day.

Usage:
    python emergency_scheduler.py                                         # demo (no booking)
    python emergency_scheduler.py --patient P0098 --doctor D01 --triage 2  # suggest only
    python emergency_scheduler.py --patient P0098 --doctor D01 --triage 2 --book
    python emergency_scheduler.py --reset          # restore original schedule, clear bookings
    streamlit run app.py                           # clickable web app
"""
import os
import argparse
from datetime import datetime
import pandas as pd
from sqlalchemy import inspect, text
from config import (BASE_DIR, PROCESSED_DIR, SCHEDULE_DATE, NO_SHOW_RISK_THRESHOLD,
                    MIN_VISITS_FOR_NO_SHOW, OVERBOOK_TIME, TRIAGE_LABELS)
from load import get_engine

REPORT_FILE = os.path.join(BASE_DIR, "reports", "emergency_decisions.csv")
BOOKINGS_TABLE = "emergency_bookings"


def priority_score(triage_level, risk_score):
    return (5 - int(triage_level)) * 10 + int(risk_score)


# ------------------------------------------------------------------ data access
def load_schedule(engine):
    schedule = pd.read_sql("SELECT * FROM upcoming_appointments", engine)
    schedule["slot_time"] = pd.to_datetime(schedule["slot_time"])
    return schedule


def load_patients(engine):
    patients = pd.read_sql("SELECT patient_id, name, age, gender, chronic_condition, risk_score, "
                           "risk_level, total_visits, no_shows FROM patient_risk_scores", engine)
    patients["no_show_rate"] = (patients["no_shows"] / patients["total_visits"]).fillna(0).round(2)
    return patients.set_index("patient_id")


def load_data(engine):
    return load_schedule(engine), load_patients(engine)


def load_bookings(engine):
    if not inspect(engine).has_table(BOOKINGS_TABLE):
        return pd.DataFrame()
    return pd.read_sql(f"SELECT * FROM {BOOKINGS_TABLE} ORDER BY booked_at DESC", engine)


# ------------------------------------------------------------------ decision logic
def find_emergency_slot(patient_id, doctor_id, triage_level, schedule, patients):
    """Return a decision dictionary explaining which slot the patient gets and why."""
    triage_level = int(triage_level)
    p = patients.loc[patient_id]
    priority = priority_score(triage_level, p["risk_score"])
    checks = []                                 # (step description, passed?) for every check made
    result = {"patient_id": patient_id, "patient_name": p["name"], "age": int(p["age"]),
              "risk_level": p["risk_level"], "triage_level": triage_level,
              "triage": f"{triage_level} ({TRIAGE_LABELS[triage_level]})",
              "priority": priority, "requested_doctor": doctor_id}

    def decide(step, action, doctor, slot, affected=None, note="", slot_id=None):
        result.update({"step": step, "action": action, "assigned_doctor": doctor,
                       "slot_time": slot, "slot_id": slot_id, "affected_patient": affected or "-",
                       "checks": checks,
                       "checks_failed": " | ".join(f"no: {c}" for c, ok in checks if not ok) or "-",
                       "note": note})
        return result

    doc = schedule[schedule["doctor_id"] == doctor_id]
    department = doc["department"].iloc[0]
    fmt = lambda t: t.strftime("%H:%M")

    # already booked with this doctor tomorrow? (e.g. button clicked twice)
    existing = doc[doc["patient_id"] == patient_id]
    if not existing.empty:
        s = existing.iloc[0]
        return decide(-1, "ALREADY BOOKED", doctor_id, fmt(s["slot_time"]),
                      note=f"{patient_id} already has a slot with {doctor_id} at {fmt(s['slot_time'])}.")

    # Step 0: life-threatening -> no appointment needed
    if triage_level == 1:
        checks.append(("Triage 1: life-threatening", True))
        return decide(0, "SEND TO EMERGENCY DEPARTMENT", "ED on-duty doctor", "Immediately",
                      note="Life-threatening case: treated in casualty without an appointment.")

    free = doc[doc["slot_status"] == "Free"]

    # Routine patients never disturb anyone
    if triage_level == 4:
        regular_free = free[free["slot_type"] == "regular"].sort_values("slot_time")
        if not regular_free.empty:
            s = regular_free.iloc[0]
            checks.append(("Free regular slot", True))
            return decide(1, "BOOK NEXT FREE REGULAR SLOT", doctor_id, fmt(s["slot_time"]),
                          note="Routine visit booked in a normal free slot.", slot_id=s["slot_id"])
        checks.append(("Free regular slot", False))
        return decide(6, "NO SLOT TOMORROW - BOOK NEXT DAY", doctor_id, "Next day",
                      note="Routine patients do not use emergency options (buffer, overbooking).")

    # Step 1: free emergency buffer slot
    buffer = free[free["slot_type"] == "buffer"]
    checks.append(("Emergency buffer slot free", not buffer.empty))
    if not buffer.empty:
        s = buffer.iloc[0]
        return decide(1, "BOOK EMERGENCY BUFFER SLOT", doctor_id, fmt(s["slot_time"]),
                      note="Buffer slot reserved in peak hour for emergencies.", slot_id=s["slot_id"])

    # Step 2: double-book a slot whose patient is likely not to come
    booked = doc[doc["slot_status"] == "Booked"].join(patients, on="patient_id", rsuffix="_p")
    already_double = doc["slot_time"][doc["slot_time"].duplicated(keep=False)]   # used before
    likely_no_show = booked[(booked["no_show_rate"] >= NO_SHOW_RISK_THRESHOLD) &
                            (booked["total_visits"] >= MIN_VISITS_FOR_NO_SHOW) &
                            (~booked["slot_time"].isin(already_double))]
    checks.append(("Likely no-show patient to double-book", not likely_no_show.empty))
    if not likely_no_show.empty:
        s = likely_no_show.sort_values("no_show_rate", ascending=False).iloc[0]
        return decide(2, "DOUBLE-BOOK LIKELY NO-SHOW SLOT", doctor_id, fmt(s["slot_time"]),
                      s["patient_id"],
                      f"{s['patient_id']} missed {int(s['no_shows'])} of {int(s['total_visits'])} "
                      f"past visits ({s['no_show_rate']:.0%}). Both are kept; confirm by phone.")

    # Step 3: another doctor in the same department
    other = schedule[(schedule["department"] == department) & (schedule["doctor_id"] != doctor_id) &
                     (schedule["slot_status"] == "Free")].sort_values("slot_time")
    checks.append((f"Another {department} doctor free", not other.empty))
    if not other.empty:
        s = other.iloc[0]
        return decide(3, "BOOK ANOTHER DOCTOR (SAME DEPARTMENT)", s["doctor_id"], fmt(s["slot_time"]),
                      note=f"{doctor_id} is full; {s['doctor_id']} ({department}) has a free slot.",
                      slot_id=s["slot_id"])

    # Step 4: reschedule the lowest-priority booked patient (only if lower than emergency)
    regular_booked = booked[booked["slot_type"].isin(["regular", "buffer"])]
    regular_booked = regular_booked.assign(priority=[
        priority_score(t, r) for t, r in zip(regular_booked["triage_level"], regular_booked["risk_score"])])
    lower = regular_booked[regular_booked["priority"] < priority].sort_values(["priority", "age"])
    checks.append(("Lower-priority patient to reschedule", not lower.empty))
    if not lower.empty:
        s = lower.iloc[0]
        return decide(4, "RESCHEDULE LOWEST-PRIORITY PATIENT", doctor_id, fmt(s["slot_time"]),
                      s["patient_id"],
                      f"{s['patient_id']} (triage {int(s['triage_level'])}, risk {s['risk_level']}, "
                      f"priority {s['priority']}) moved to next available day and notified by SMS.",
                      slot_id=s["slot_id"])

    # Step 5: last resort - next free time after the last regular slot
    taken = set(doc["slot_time"].dt.strftime("%H:%M"))
    t = pd.Timestamp(f"{SCHEDULE_DATE} {OVERBOOK_TIME}")
    while t.strftime("%H:%M") in taken:
        t += pd.Timedelta(minutes=30)
    return decide(5, "OVERBOOK EXTRA SLOT", doctor_id, fmt(t),
                  note="Doctor sees the patient after the last regular slot.")


# ------------------------------------------------------------------ booking (writes to MySQL)
def book(decision, engine):
    """Apply a decision to the schedule in MySQL and log it. Returns a confirmation message."""
    step = decision["step"]
    if step == -1:
        return f"No change: {decision['note']}"
    schedule = load_schedule(engine)
    pid, triage = decision["patient_id"], decision["triage_level"]
    new_slot_id = f"E{datetime.now().strftime('%H%M%S%f')[:9]}"

    def add_row(doctor, time_str, slot_type):
        dept = schedule.loc[schedule["doctor_id"] == doctor, "department"].iloc[0]
        return pd.DataFrame([{"slot_id": new_slot_id, "doctor_id": doctor, "department": dept,
                              "slot_time": pd.Timestamp(f"{SCHEDULE_DATE} {time_str}"),
                              "slot_type": slot_type, "patient_id": pid, "triage_level": triage,
                              "slot_status": "Booked"}])

    if step in (1, 3, 4):                        # take over an existing slot
        row = schedule["slot_id"] == decision["slot_id"]
        schedule.loc[row, ["patient_id", "triage_level", "slot_status"]] = [pid, triage, "Booked"]
    elif step == 2:                              # extra patient in the same time slot
        schedule = pd.concat([schedule, add_row(decision["assigned_doctor"], decision["slot_time"],
                                                "double_booked")], ignore_index=True)
    elif step == 5:                              # extra slot after hours
        schedule = pd.concat([schedule, add_row(decision["assigned_doctor"], decision["slot_time"],
                                                "overbooked")], ignore_index=True)
    # step 0 (Emergency Department) and 6 (next day) do not change tomorrow's schedule

    schedule["triage_level"] = schedule["triage_level"].astype("Int64")
    schedule.sort_values(["doctor_id", "slot_time"]).to_sql(
        "upcoming_appointments", engine, if_exists="replace", index=False)

    log = {k: decision[k] for k in ["patient_id", "patient_name", "triage", "priority",
                                    "requested_doctor", "step", "action", "assigned_doctor",
                                    "slot_time", "affected_patient", "note"]}
    log["booked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pd.DataFrame([log]).to_sql(BOOKINGS_TABLE, engine, if_exists="append", index=False)

    if step == 0:
        return f"{pid} sent to the Emergency Department. Logged."
    if step == 6:
        return f"No free slot tomorrow; {pid} to be booked for the next day. Logged."
    msg = f"Booked {pid} with {decision['assigned_doctor']} at {decision['slot_time']}."
    if step == 4:
        msg += f" {decision['affected_patient']} has been moved to the next day."
    return msg


def reset(engine):
    """Restore tomorrow's schedule from the pipeline output and clear all emergency bookings."""
    original = pd.read_csv(os.path.join(PROCESSED_DIR, "upcoming_appointments.csv"),
                           parse_dates=["slot_time"])
    original["triage_level"] = original["triage_level"].astype("Int64")
    original.to_sql("upcoming_appointments", engine, if_exists="replace", index=False)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {BOOKINGS_TABLE}"))
    return "Schedule restored to original and emergency bookings cleared."


# ------------------------------------------------------------------ command line
def print_decision(d, title=None):
    if title:
        print(f"\n{'=' * 72}\n SCENARIO: {title}\n{'=' * 72}")
    print(f" Patient   : {d['patient_id']} {d['patient_name']}, age {d['age']}, risk {d['risk_level']}")
    print(f" Triage    : {d['triage']}   ->  priority score {d['priority']}")
    print(f" Requested : {d['requested_doctor']} on {SCHEDULE_DATE}")
    print(f" Checked   : {d['checks_failed']}")
    print(f" DECISION  : Step {d['step']} - {d['action']}")
    if d["step"] == 0:
        print("             Patient goes to casualty now - no appointment needed")
    elif d["step"] in (-1, 6):
        pass
    else:
        print(f"             Doctor {d['assigned_doctor']} at {d['slot_time']}")
    print(f" Why       : {d['note']}")


DEMO_SCENARIOS = [
    # (title,                                    patient, doctor, triage)
    ("Heart attack symptoms (life-threatening)",   "P0101", "D01", 1),
    ("General Medicine - buffer slot available",   "P0149", "D03", 2),
    ("Cardiology D01 fully booked",                "P0098", "D01", 2),
    ("Orthopedics D06 fully booked",               "P0024", "D06", 2),
    ("Neurology fully booked (only one doctor)",   "P0145", "D09", 2),
    ("Cardiology D02 full of urgent follow-ups",   "P0057", "D02", 3),
]


def main():
    parser = argparse.ArgumentParser(description="Emergency appointment scheduler")
    parser.add_argument("--patient"); parser.add_argument("--doctor")
    parser.add_argument("--triage", type=int, choices=[1, 2, 3, 4])
    parser.add_argument("--book", action="store_true", help="save the booking to the database")
    parser.add_argument("--reset", action="store_true", help="restore the original schedule")
    args = parser.parse_args()
    engine = get_engine()

    if args.reset:
        print(reset(engine)); return

    schedule, patients = load_data(engine)
    if args.patient and args.doctor and args.triage:
        if args.patient not in patients.index:
            print(f"Unknown patient id: {args.patient}"); return
        if args.doctor not in set(schedule["doctor_id"]):
            print(f"Unknown doctor id: {args.doctor}"); return
        d = find_emergency_slot(args.patient, args.doctor, args.triage, schedule, patients)
        print_decision(d)
        if args.book:
            print(f"\n BOOKING   : {book(d, engine)}")
        else:
            print("\n (suggestion only - add --book to save it)")
        return

    decisions = []
    for title, pid, doctor, triage in DEMO_SCENARIOS:
        d = find_emergency_slot(pid, doctor, triage, schedule, patients)
        print_decision(d, title)
        decisions.append({"scenario": title, **{k: v for k, v in d.items() if k != "checks"}})
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    pd.DataFrame(decisions).to_csv(REPORT_FILE, index=False)
    print(f"\nAll decisions saved to reports/{os.path.basename(REPORT_FILE)}")


if __name__ == "__main__":
    main()
