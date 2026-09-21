"""
visualize.py
Creates simple dashboard charts from the database and saves them as PNG files
in the reports/ folder. Run after pipeline.py:  python visualize.py
"""
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from config import BASE_DIR
from load import get_engine

OUT_DIR = os.path.join(BASE_DIR, "reports")


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, name), dpi=150)
    plt.close(fig)
    print(f"Saved reports/{name}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    engine = get_engine()
    appts = pd.read_sql("SELECT * FROM appointments WHERE status = 'Completed'", engine)
    risk = pd.read_sql("SELECT risk_level FROM patient_risk_scores", engine)

    # 1. Average waiting time by department
    dept = appts.groupby("department")["waiting_minutes"].mean().sort_values()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(dept.index, dept.values, color="#2E75B6")
    ax.set_xlabel("Average waiting time (minutes)")
    ax.set_title("Average waiting time by department")
    for i, v in enumerate(dept.values):
        ax.text(v + 0.5, i, f"{v:.0f}", va="center")
    save(fig, "wait_time_by_department.png")

    # 2. Average waiting time by hour of day
    hour = appts.groupby("appointment_hour")["waiting_minutes"].mean()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(hour.index, hour.values, marker="o", color="#C0504D")
    ax.set_xticks(hour.index)
    ax.set_xticklabels([f"{h}:00" for h in hour.index])
    ax.set_ylabel("Average waiting time (minutes)")
    ax.set_title("Waiting time by hour of day (peak hours)")
    ax.grid(alpha=0.3)
    save(fig, "wait_time_by_hour.png")

    # 3. Patients by risk level
    counts = risk["risk_level"].value_counts().reindex(["Low", "Medium", "High"])
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(counts.index, counts.values, color=["#70AD47", "#FFC000", "#C00000"])
    ax.set_ylabel("Number of patients")
    ax.set_title("Patients by risk level")
    for i, v in enumerate(counts.values):
        ax.text(i, v + 1, str(v), ha="center")
    save(fig, "risk_level_distribution.png")


if __name__ == "__main__":
    main()
