-- Operational checks. Every query should return zero rows unless noted.

-- Attendance that cannot be tied to an enrollment (known source gap: 21 rows).
SELECT class_code, course_name, emp_code, count(*) AS attendance_rows
FROM attendance_log
WHERE enrollment_id IS NULL
GROUP BY class_code, course_name, emp_code
ORDER BY attendance_rows DESC;

-- One session order maps to multiple actual timestamps in the source.
SELECT class_code, course_name, session_order,
       count(DISTINCT session_date) AS distinct_times
FROM attendance_log
GROUP BY class_code, course_name, session_order
HAVING count(DISTINCT session_date) > 1
ORDER BY distinct_times DESC, class_code, course_name, session_order;

-- Current snapshot that cannot be linked to one explicit enrollment.
SELECT s.emp_code, s.current_course, s.latest_class_code, s.latest_course_name
FROM students s
WHERE s.current_course IS NOT NULL
  AND s.current_enrollment_id IS NULL;

-- Session foreign key should make this impossible after migration.
SELECT a.attendance_id
FROM attendance_log a
LEFT JOIN class_sessions cs ON cs.session_id = a.session_id
WHERE cs.session_id IS NULL;
