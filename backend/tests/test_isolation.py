"""User B must never read or modify user A's data by changing IDs (SRS FR-006, T-150)."""
from tests.conftest import SAMPLE_JD

RESUME_TEXT = """Priya Sharma
priya.s@example.com | +91 98765 43210
EDUCATION
Example Institute of Technology, B.Tech Computer Science, 2022 - 2026
SKILLS
Python, SQL, Git, FastAPI
PROJECTS
Campus Events API
- Made backend for event registration using FastAPI and PostgreSQL
- Wrote SQL queries to generate attendance reports for organisers
- Deployed the service and documented the REST endpoints for the student council
""" * 2


def _setup_user_a(c):
    t = c.post("/api/v1/targets", json={"role_slug": "backend-dev", "daily_minutes": 60}).json()["target"]
    c.post(f"/api/v1/targets/{t['id']}/job-description", json={"text": SAMPLE_JD})
    r = c.post("/api/v1/resumes/from-text", json={"text": RESUME_TEXT}).json()
    a = c.post(f"/api/v1/targets/{t["id"]}/assessments", json={"kind": "diagnostic"}).json()
    assert "id" in a, a
    plan = c.post(f"/api/v1/targets/{t['id']}/plans").json()
    s = c.post(f"/api/v1/targets/{t['id']}/interviews", json={"type": "technical"}).json()
    return t, r, a, plan, s


def test_cross_user_access_returns_404_everywhere(login, fake_ai):
    a = login("owner@example.com")
    t, resume, assessment, plan, session = _setup_user_a(a)
    b = login("intruder@example.com")
    tid, rid, aid, sid = t["id"], resume["resume_id"], assessment["id"], session["id"]
    vid = resume["version_id"]
    turn_id = session["turns"][0]["id"]
    task_id = plan["days"][0]["tasks"][0]["id"]
    gets = [f"/api/v1/targets/{tid}", f"/api/v1/targets/{tid}/requirements", f"/api/v1/targets/{tid}/dashboard",
            f"/api/v1/targets/{tid}/gap-reports/latest", f"/api/v1/targets/{tid}/readiness",
            f"/api/v1/targets/{tid}/plans/active", f"/api/v1/targets/{tid}/progress",
            f"/api/v1/targets/{tid}/assessments", f"/api/v1/targets/{tid}/interviews",
            f"/api/v1/resumes/{rid}", f"/api/v1/resumes/{rid}/versions", f"/api/v1/resumes/{rid}/versions/{vid}",
            f"/api/v1/assessments/{aid}", f"/api/v1/assessments/{aid}/result", f"/api/v1/interviews/{sid}",
            f"/api/v1/practice/attempts?target_id={tid}", f"/api/v1/practice/summary?target_id={tid}",
            f"/api/v1/resumes/{rid}/analyses/latest?target_id={tid}"]
    for path in gets:
        r = b.get(path)
        assert r.status_code == 404, (path, r.status_code)
        assert r.json()["error"]["code"] == "NOT_FOUND"
    writes = [("patch", f"/api/v1/targets/{tid}", {"daily_minutes": 90}),
              ("post", f"/api/v1/targets/{tid}/job-description", {"text": SAMPLE_JD}),
              ("put", f"/api/v1/assessments/{aid}/items/1/response", {"response": {"selected": ["a"]}}),
              ("post", f"/api/v1/assessments/{aid}/submit", None),
              ("post", f"/api/v1/interviews/{sid}/turns/{turn_id}/answer", {"answer_text": "x " * 30}),
              ("patch", f"/api/v1/plan-tasks/{task_id}", {"status": "skipped"}),
              ("delete", f"/api/v1/resumes/{rid}", None),
              ("post", f"/api/v1/resumes/{rid}/analyses", {"target_id": tid}),
              ("post", f"/api/v1/targets/{tid}/plans", None)]
    for method, path, body in writes:
        r = getattr(b, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, path, r.status_code, r.text)
    # A's data is untouched
    assert a.get(f"/api/v1/resumes/{rid}").status_code == 200
    assert a.get(f"/api/v1/targets/{tid}").json()["daily_minutes"] == 60


def test_lists_only_show_own_rows(login, fake_ai):
    a = login("lista@example.com")
    _setup_user_a(a)
    b = login("listb@example.com")
    assert b.get("/api/v1/targets").json() == []
    assert b.get("/api/v1/resumes").json() == []


def test_mixed_ownership_ids_are_rejected(login, fake_ai):
    a = login("mixa@example.com")
    t, resume, *_ = _setup_user_a(a)
    b = login("mixb@example.com")
    tb = b.post("/api/v1/targets", json={"role_slug": "frontend-dev", "daily_minutes": 60}).json()["target"]
    r = b.post(f"/api/v1/resumes/{resume['resume_id']}/analyses", json={"target_id": tb["id"]})
    assert r.status_code == 404
    r = a.post(f"/api/v1/resumes/{resume['resume_id']}/analyses", json={"target_id": tb["id"]})
    assert r.status_code == 404
