-- ============================================================
-- analysis_queries.sql
-- Business questions answered from the loaded tables.
-- Run in MySQL Workbench, or automatically via analysis.py
-- ============================================================

-- name: Average waiting time by department (Goal: reduce waiting time)
SELECT department,
       COUNT(*)                         AS completed_visits,
       ROUND(AVG(waiting_minutes), 1)   AS avg_wait_minutes,
       ROUND(MAX(waiting_minutes), 1)   AS max_wait_minutes
FROM appointments
WHERE status = 'Completed'
GROUP BY department
ORDER BY avg_wait_minutes DESC;

-- name: Peak hours with longest waiting time (Goal: reduce waiting time)
SELECT appointment_hour,
       COUNT(*)                         AS visits,
       ROUND(AVG(waiting_minutes), 1)   AS avg_wait_minutes
FROM appointments
WHERE status = 'Completed'
GROUP BY appointment_hour
ORDER BY appointment_hour;

-- name: No-show rate by department (Goal: operational efficiency)
SELECT department,
       COUNT(*)                                     AS total_appointments,
       SUM(is_no_show)                              AS no_shows,
       ROUND(100.0 * SUM(is_no_show) / COUNT(*), 1) AS no_show_pct
FROM appointments
GROUP BY department
ORDER BY no_show_pct DESC;

-- name: Patients by risk level (Goal: predict high-risk patients)
SELECT risk_level, COUNT(*) AS patients
FROM patient_risk_scores
GROUP BY risk_level
ORDER BY patients DESC;

-- name: Top 10 patients by risk score (Goal: predict high-risk patients)
SELECT patient_id, name, age, chronic_condition, abnormal_lab_count,
       abnormal_vital_pct, critical_symptom_notes, risk_score
FROM patient_risk_scores
WHERE risk_level IN ('High', 'Medium')
ORDER BY risk_score DESC, age DESC
LIMIT 10;

-- name: Most common abnormal lab tests (Goal: improve patient care)
SELECT test_name,
       SUM(is_abnormal)                              AS abnormal_results,
       ROUND(100.0 * SUM(is_abnormal) / COUNT(*), 1) AS abnormal_pct
FROM lab_results
GROUP BY test_name
ORDER BY abnormal_results DESC;

-- name: Tomorrow's schedule - booked slots per doctor (input for emergency scheduling)
SELECT doctor_id, department,
       SUM(CASE WHEN slot_status = 'Booked' THEN 1 ELSE 0 END) AS booked_slots,
       COUNT(*)                                                AS total_slots,
       SUM(CASE WHEN slot_type = 'buffer' AND slot_status = 'Free' THEN 1 ELSE 0 END) AS buffer_free
FROM upcoming_appointments
GROUP BY doctor_id, department
ORDER BY doctor_id;
