from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from tests.test_api_auth import ORIGIN, client_for


def _login(client, username="pytest_editor", password="editor-pass"):
    response=client.post("/api/auth/login",headers={"Origin":ORIGIN},json={"username":username,"password":password})
    assert response.status_code==200
    return response.json()


def test_editor_creates_class_first_run_and_pic_atomically(database_url, factory, seed_ids):
    class_code=f"API{factory.unique():04d}"
    pool,client=client_for(database_url)
    try:
        with client:
            auth=_login(client)
            response=client.post("/api/administration/classes",headers={"X-CSRF-Token":auth["csrf_token"]},json={
                "class_code":class_code,"display_name":"API Atomic Class","course_id":seed_ids["course"],
                "start_date":"2026-09-01","capacity":12,"status":"active","pic_employee_id":None,"pic_label":"People Team",
            })
            listed=client.get(f"/api/administration/classes?q={class_code}&page_size=10")
        assert response.status_code==200
        assert response.json()["values"]["run_number"]==1
        assert listed.json()["items"][0]["current_pic"]=="People Team"
        assert listed.json()["items"][0]["course_run_count"]==1
        cohort_id=response.json()["values"]["cohort_id"]
        assert factory.one("SELECT count(*) FROM audit_events WHERE entity_key=%s",(str(cohort_id),))[0]>=1
    finally: pool.closeall()


def test_failed_atomic_class_creation_leaves_no_partial_class(database_url, factory):
    class_code=f"BAD{factory.unique():04d}"
    pool,client=client_for(database_url)
    try:
        with client:
            auth=_login(client)
            response=client.post("/api/administration/classes",headers={"X-CSRF-Token":auth["csrf_token"]},json={
                "class_code":class_code,"display_name":"Must Roll Back","course_id":999999,
                "start_date":"2026-09-01","capacity":8,"status":"active","pic_label":"People Team",
            })
        assert response.status_code==404
        assert factory.one("SELECT count(*) FROM cohorts WHERE class_code=%s",(class_code,))[0]==0
    finally: pool.closeall()


def test_editor_creates_two_units_then_corrects_and_cancels_schedule_with_audit(database_url, factory):
    _,run_id=factory.cohort_run()
    pool,client=client_for(database_url)
    try:
        with client:
            auth=_login(client)
            created=client.post(f"/api/administration/course-runs/{run_id}/meetings",headers={"X-CSRF-Token":auth["csrf_token"]},json={
                "starts_at":"2026-09-03T09:00:00+07:00","duration_minutes":120,"first_sequence_in_run":1,
                "unit_count":2,"unit_type":"normal","status":"planned",
            })
            meeting_id=created.json()["entity_id"]
            corrected=client.patch(f"/api/administration/meetings/{meeting_id}",headers={"X-CSRF-Token":auth["csrf_token"]},json={
                "course_run_id":run_id,"starts_at":"2026-09-03T10:00:00+07:00","duration_minutes":90,
                "status":"planned","reason":"Teacher requested a later start",
            })
            cancelled=client.post(f"/api/administration/meetings/{meeting_id}/cancellation",headers={"X-CSRF-Token":auth["csrf_token"]},json={"reason":"Class cancelled by owner"})
            schedule=client.get(f"/api/administration/schedule?course_run_id={run_id}")
        assert created.status_code==200 and len(created.json()["values"]["session_unit_ids"])==2
        assert corrected.status_code==200 and cancelled.status_code==200
        row=next(item for item in schedule.json()["items"] if item["meeting_id"]==meeting_id)
        assert row["duration_minutes"]==90 and row["status"]=="cancelled"
        assert [unit["sequence_in_run"] for unit in row["units"]]==[1,2]
        audit=factory.one("""SELECT details->'before',details->'after' FROM audit_events
                             WHERE action='meeting.correct' AND entity_key=%s""",(str(meeting_id),))
        assert audit[0]["duration_minutes"]==120 and audit[1]["duration_minutes"]==90
        assert factory.one("SELECT details->>'reason' FROM audit_events WHERE action='meeting.cancel' AND entity_key=%s",(str(meeting_id),))[0]=="Class cancelled by owner"
    finally: pool.closeall()


def test_editor_assigns_pic_adds_run_changes_lifecycle_and_adds_units(database_url, factory, seed_ids):
    cohort_id, _ = factory.cohort_run()
    learner = factory.onboard(factory.one("SELECT course_run_id FROM course_runs WHERE cohort_id=%s", (cohort_id,))[0])
    employee_id = learner.values["employee_id"]
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            assigned = client.post(
                f"/api/administration/cohorts/{cohort_id}/pic-assignments",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"pic_employee_id": employee_id, "pic_label": None, "start_date": "2026-09-01"},
            )
            created_run = client.post(
                f"/api/administration/cohorts/{cohort_id}/course-runs",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"course_id": seed_ids["course"], "start_date": "2026-09-02"},
            )
            run_id = created_run.json()["entity_id"]
            activated = client.post(
                f"/api/administration/course-runs/{run_id}/status",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"status": "active", "end_date": None},
            )
            meeting = client.post(
                f"/api/administration/course-runs/{run_id}/meetings",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"starts_at": "2026-09-03T09:00:00+07:00", "duration_minutes": 120,
                      "first_sequence_in_run": 1, "unit_count": 1, "unit_type": "normal", "status": "planned"},
            )
            added = client.post(
                f"/api/administration/meetings/{meeting.json()['entity_id']}/session-units",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"course_run_id": run_id, "first_sequence_in_run": 2, "unit_count": 1, "unit_type": "normal"},
            )

        assert [assigned.status_code, created_run.status_code, activated.status_code, meeting.status_code, added.status_code] == [200] * 5
        assert factory.one("SELECT pic_employee_id FROM cohort_pic_assignments WHERE cohort_id=%s AND end_date IS NULL", (cohort_id,))[0] == employee_id
        assert factory.one("SELECT status FROM course_runs WHERE course_run_id=%s", (run_id,))[0] == "active"
        assert factory.one(
            "SELECT array_agg(unit_number_in_meeting ORDER BY unit_number_in_meeting) FROM session_units WHERE meeting_id=%s",
            (meeting.json()["entity_id"],),
        )[0] == [1, 2]
    finally:
        pool.closeall()


def test_administration_permissions_validation_and_concurrent_run_numbers(database_url, factory, seed_ids):
    cohort_id,_=factory.cohort_run()
    pool,client=client_for(database_url)
    try:
        with client:
            viewer=_login(client,"pytest_viewer","viewer-pass")
            assert client.get("/api/administration/classes").status_code==403
            forbidden=client.post("/api/administration/classes",headers={"X-CSRF-Token":viewer["csrf_token"]},json={})
            assert forbidden.status_code==403
            client.post("/api/auth/logout",headers={"X-CSRF-Token":viewer["csrf_token"]})
            editor=_login(client)
            naive=client.post(f"/api/administration/course-runs/{factory.one('SELECT course_run_id FROM course_runs WHERE cohort_id=%s',(cohort_id,))[0]}/meetings",headers={"X-CSRF-Token":editor["csrf_token"]},json={
                "starts_at":"2026-09-03T09:00:00","duration_minutes":60,"first_sequence_in_run":1,"unit_count":1,"unit_type":"normal","status":"planned",
            })
            assert naive.status_code==422
    finally: pool.closeall()

    barrier=Barrier(2)
    def submit():
        thread_pool,thread_client=client_for(database_url)
        try:
            with thread_client:
                auth=_login(thread_client)
                barrier.wait()
                return thread_client.post(f"/api/administration/cohorts/{cohort_id}/course-runs",headers={"X-CSRF-Token":auth["csrf_token"]},json={"course_id":seed_ids["course"],"start_date":"2026-10-01"})
        finally: thread_pool.closeall()
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses=list(executor.map(lambda _:submit(),range(2)))
    assert [response.status_code for response in responses]==[200,200]
    assert sorted(response.json()["values"]["run_number"] for response in responses)==[2,3]
