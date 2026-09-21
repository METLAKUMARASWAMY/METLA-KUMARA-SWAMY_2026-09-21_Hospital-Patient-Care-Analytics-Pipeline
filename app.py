"""
app.py  -  Hospital Patient Care web app (clickable interface)
Run:  streamlit run app.py
Pages:
    Dashboard          - key numbers and charts from the pipeline output
    Emergency Booking  - pick patient, doctor, triage -> Find slot -> Confirm booking
    Doctor Schedule    - tomorrow's slots for every doctor (updates after each booking)
    Bookings Log       - all emergency bookings, reset button
    Run Pipeline       - generate data and run the ETL pipeline with one click
"""
import os
import sys
import subprocess
import pandas as pd
import streamlit as st
from sqlalchemy import inspect
from config import BASE_DIR, TRIAGE_LABELS, SCHEDULE_DATE, EMERGENCY_BUFFER_SLOT
from load import get_engine
from emergency_scheduler import (find_emergency_slot, book, reset, load_schedule,
                                 load_patients, load_bookings, priority_score)

st.set_page_config(page_title="Hospital Patient Care", page_icon="🏥", layout="wide")


# ------------------------------------------------------------------ helpers
@st.cache_resource
def engine():
    return get_engine()


def tables_ready(eng):
    names = inspect(eng).get_table_names()
    return all(t in names for t in ["patient_risk_scores", "upcoming_appointments", "appointments"])


def run_script(script):
    result = subprocess.run([sys.executable, script], cwd=BASE_DIR, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr)


STEP_STYLE = {-1: "info", 0: "error", 1: "success", 2: "warning", 3: "success",
              4: "warning", 5: "warning", 6: "info"}


# ------------------------------------------------------------------ connection
try:
    eng = engine()
    ready = tables_ready(eng)
except Exception as e:
    st.error("Could not connect to MySQL. Check that MySQL is running and the password in "
             "config.py (or the DB_PASSWORD environment variable) is correct.")
    st.code(str(e).splitlines()[0])
    st.stop()

st.sidebar.title("🏥 Hospital Patient Care")
st.sidebar.caption("ETL pipeline + emergency scheduling")
page = st.sidebar.radio("Go to", ["📊 Dashboard", "🚑 Emergency Booking", "📅 Doctor Schedule",
                                  "📋 Bookings Log", "⚙️ Run Pipeline"])
st.sidebar.divider()
st.sidebar.caption(f"Schedule date: **{SCHEDULE_DATE}**")
st.sidebar.caption(f"Emergency buffer slot: **{EMERGENCY_BUFFER_SLOT}**")

if not ready and page != "⚙️ Run Pipeline":
    st.warning("The database tables are not loaded yet. Open **⚙️ Run Pipeline** in the sidebar "
               "and click **Run ETL pipeline** first.")
    st.stop()


# ------------------------------------------------------------------ 📊 Dashboard
if page == "📊 Dashboard":
    st.title("📊 Dashboard")
    appts = pd.read_sql("SELECT * FROM appointments", eng)
    risk = load_patients(eng)
    sched = load_schedule(eng)
    done = appts[appts["status"] == "Completed"]

    c = st.columns(5)
    c[0].metric("Patients", len(risk))
    c[1].metric("High-risk patients", int((risk["risk_level"] == "High").sum()))
    c[2].metric("Avg waiting time", f"{done['waiting_minutes'].mean():.0f} min")
    c[3].metric("No-show rate", f"{appts['is_no_show'].mean():.1%}")
    c[4].metric("Tomorrow's slots booked",
                f"{(sched['slot_status'] == 'Booked').sum()} / {len(sched)}")

    left, right = st.columns(2)
    with left:
        st.subheader("Average waiting time by department")
        st.bar_chart(done.groupby("department")["waiting_minutes"].mean().round(1)
                     .sort_values(ascending=False), y_label="minutes")
        st.subheader("Patients by risk level")
        st.bar_chart(risk["risk_level"].value_counts().reindex(["Low", "Medium", "High"]),
                     y_label="patients")
    with right:
        st.subheader("Average waiting time by hour")
        by_hour = done.groupby("appointment_hour")["waiting_minutes"].mean().round(1)
        by_hour.index = [f"{h:02d}:00" for h in by_hour.index]
        st.line_chart(by_hour, y_label="minutes")
        st.subheader("High-risk patients")
        st.dataframe(risk[risk["risk_level"] == "High"]
                     .sort_values("risk_score", ascending=False)
                     [["name", "age", "chronic_condition", "risk_score"]], height=300)


# ------------------------------------------------------------------ 🚑 Emergency Booking
elif page == "🚑 Emergency Booking":
    st.title("🚑 Emergency Booking")
    st.caption("Choose the patient, doctor and triage level, then click **Find best slot**. "
               "Review the decision and click **Confirm booking** to save it.")
    patients = load_patients(eng)
    sched = load_schedule(eng)

    if "message" in st.session_state:
        st.success(st.session_state.pop("message"))

    form, result = st.columns([2, 3], gap="large")
    with form:
        pid = st.selectbox(
            "Patient", patients.index,
            format_func=lambda p: f"{p} · {patients.loc[p, 'name']} · {patients.loc[p, 'risk_level']} "
                                  f"risk ({patients.loc[p, 'risk_score']})")
        load_by_doc = sched.groupby("doctor_id").agg(
            dept=("department", "first"), booked=("slot_status", lambda s: (s == "Booked").sum()),
            total=("slot_id", "count"))
        doctor = st.selectbox(
            "Doctor", load_by_doc.index,
            format_func=lambda d: f"{d} · {load_by_doc.loc[d, 'dept']} · "
                                  f"{load_by_doc.loc[d, 'booked']}/{load_by_doc.loc[d, 'total']} booked")
        triage = st.radio("Triage level (set by the nurse)", [1, 2, 3, 4], index=1,
                          format_func=lambda t: f"{t} – {TRIAGE_LABELS[t]}"
                          + (" (life-threatening)" if t == 1 else ""))

        p = patients.loc[pid]
        with st.container(border=True):
            st.markdown(f"**{p['name']}** · {p['age']} yrs · {p['gender']}")
            st.markdown(f"Chronic condition: **{p['chronic_condition']}**")
            st.markdown(f"Risk: **{p['risk_level']}** (score {p['risk_score']}) · "
                        f"missed {p['no_shows']} of {p['total_visits']} past visits")
            st.markdown(f"Priority score = (5 − {triage}) × 10 + {p['risk_score']} = "
                        f"**{priority_score(triage, p['risk_score'])}**")

        if st.button("🔍 Find best slot", type="primary", use_container_width=True):
            st.session_state["decision"] = find_emergency_slot(pid, doctor, triage, sched, patients)
            st.session_state["request"] = (pid, doctor, triage)

    with result:
        d = st.session_state.get("decision")
        if d is None or st.session_state.get("request") != (pid, doctor, triage):
            st.info("The decision will appear here after you click **Find best slot**.")
        else:
            st.subheader("Checks made (least disruptive option first)")
            for name, ok in d["checks"]:
                st.markdown(f"{'✅' if ok else '❌'} {name}")
            title = f"Step {d['step']}: {d['action']}" if d["step"] >= 0 else d["action"]
            where = ("Go to casualty immediately" if d["step"] == 0 else
                     f"Doctor **{d['assigned_doctor']}** at **{d['slot_time']}**")
            getattr(st, STEP_STYLE[d["step"]])(f"**{title}**  \n{where}  \n{d['note']}")
            if d["affected_patient"] != "-":
                st.caption(f"Other patient affected: {d['affected_patient']}")

            if d["step"] != -1:
                b1, b2 = st.columns(2)
                if b1.button("✅ Confirm booking", type="primary", use_container_width=True):
                    st.session_state["message"] = book(d, eng)
                    st.session_state.pop("decision")
                    st.rerun()
                if b2.button("✖ Cancel", use_container_width=True):
                    st.session_state.pop("decision")
                    st.rerun()


# ------------------------------------------------------------------ 📅 Doctor Schedule
elif page == "📅 Doctor Schedule":
    st.title(f"📅 Doctor Schedule – {SCHEDULE_DATE}")
    sched = load_schedule(eng)
    patients = load_patients(eng)
    bookings = load_bookings(eng)
    emergency_keys = set()
    if not bookings.empty:
        emergency_keys = set(zip(bookings["patient_id"], bookings["assigned_doctor"]))

    def symbol(row):
        if row["slot_status"] == "Free":
            return "🟡 buffer" if row["slot_type"] == "buffer" else "🟢 free"
        if (row["patient_id"], row["doctor_id"]) in emergency_keys:
            return "🚑 " + row["patient_id"]
        return "🔴 " + row["patient_id"]

    sched["time"] = sched["slot_time"].dt.strftime("%H:%M")
    sched["cell"] = sched.apply(symbol, axis=1)
    grid = (sched.groupby(["doctor_id", "department", "time"])["cell"].agg(" + ".join)
            .unstack("time").fillna(""))
    st.caption("🟢 free slot · 🟡 free emergency buffer · 🔴 booked · 🚑 emergency booking")
    st.dataframe(grid, height=420)

    st.subheader("Slot details")
    doctor = st.selectbox("Doctor", sorted(sched["doctor_id"].unique()))
    detail = sched[sched["doctor_id"] == doctor].sort_values("slot_time")
    detail = detail.join(patients[["name", "risk_level"]], on="patient_id")
    st.dataframe(detail[["time", "slot_type", "slot_status", "patient_id", "name",
                         "risk_level", "triage_level"]], hide_index=True)


# ------------------------------------------------------------------ 📋 Bookings Log
elif page == "📋 Bookings Log":
    st.title("📋 Emergency Bookings Log")
    bookings = load_bookings(eng)
    if bookings.empty:
        st.info("No emergency bookings yet. Make one on the **🚑 Emergency Booking** page.")
    else:
        st.metric("Emergency bookings", len(bookings))
        st.dataframe(bookings[["booked_at", "patient_id", "patient_name", "triage", "priority",
                               "requested_doctor", "action", "assigned_doctor", "slot_time",
                               "affected_patient"]], hide_index=True)
    st.divider()
    st.subheader("Reset")
    st.caption("Restore tomorrow's original schedule and delete all emergency bookings "
               "(useful before a demo).")
    if st.button("↺ Reset schedule"):
        st.success(reset(eng))


# ------------------------------------------------------------------ ⚙️ Run Pipeline
elif page == "⚙️ Run Pipeline":
    st.title("⚙️ Run Pipeline")
    st.caption("Runs the same scripts as the terminal commands. Running the pipeline reloads "
               "all tables and clears emergency bookings.")
    c1, c2 = st.columns(2)
    if c1.button("1️⃣ Generate sample data", use_container_width=True):
        with st.spinner("Generating source files..."):
            code, out = run_script("generate_data.py")
        (st.success if code == 0 else st.error)("Done" if code == 0 else "Failed")
        st.code(out)
    if c2.button("2️⃣ Run ETL pipeline", type="primary", use_container_width=True):
        with st.spinner("Extract → Transform → Validate → Load..."):
            code, out = run_script("pipeline.py")
        if code == 0:
            st.success("Pipeline finished successfully. All pages now use the fresh data.")
        else:
            st.error("Pipeline failed – see the log below.")
        st.code(out)
