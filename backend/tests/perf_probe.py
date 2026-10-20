"""Developer tool (not collected by pytest): count SQL statements per request on the test database.

    .venv/bin/python -m pytest tests/perf_probe.py -q -s -p no:cacheprovider
"""
from collections import Counter

from sqlalchemy import event

from app.core.db import get_engine
from tests.test_assessment_and_gaps import _answer_all
from tests.test_isolation import RESUME_TEXT
from tests.conftest import SAMPLE_JD

COUNTS: Counter = Counter()
CURRENT = {"name": None}


@event.listens_for(get_engine(), "before_cursor_execute")
def _count(conn, cursor, statement, params, context, executemany):
    if CURRENT["name"]:
        COUNTS[CURRENT["name"]] += 1


def call(name, fn):
    CURRENT["name"] = name
    r = fn()
    CURRENT["name"] = None
    assert r.status_code < 400, (name, r.text[:300])
    return r.json() if r.content else None


def test_probe(client, db):
    t = call("create target", lambda: client.post("/api/v1/targets", json={"role_slug": "backend-dev",
                                                                            "daily_minutes": 60}))["target"]
    tid = t["id"]
    jd = call("submit JD", lambda: client.post(f"/api/v1/targets/{tid}/job-description", json={"text": SAMPLE_JD}))
    items = [{"id": r["id"], "skill_slug": (r["skill"] or {}).get("slug"), "raw_phrase": r["raw_phrase"],
              "requirement_level": r["requirement_level"], "category": r["category"]} for r in jd["requirements"]]
    call("confirm reqs", lambda: client.put(f"/api/v1/targets/{tid}/requirements", json={"requirements": items}))
    res = call("import resume", lambda: client.post("/api/v1/resumes/from-text", json={"text": RESUME_TEXT}))
    v = call("save version", lambda: client.post(f"/api/v1/resumes/{res['resume_id']}/versions", json={
        "content": res["content"], "base_version_id": res["version_id"], "mark_reviewed": True}))
    st = call("start diagnostic", lambda: client.post(f"/api/v1/targets/{tid}/assessments", json={"kind": "diagnostic"}))
    _answer_all(client, st, correct=False, db=db)
    call("submit diagnostic", lambda: client.post(f"/api/v1/assessments/{st['id']}/submit"))
    call("gap report", lambda: client.get(f"/api/v1/targets/{tid}/gap-reports/latest"))
    call("plan", lambda: client.post(f"/api/v1/targets/{tid}/plans"))
    call("plan get", lambda: client.get(f"/api/v1/targets/{tid}/plans/active"))
    call("dashboard", lambda: client.get(f"/api/v1/targets/{tid}/dashboard"))
    call("dashboard home", lambda: client.get("/api/v1/dashboard"))
    call("practice q", lambda: client.get("/api/v1/practice/questions", params={"target_id": tid, "skill": "sql"}))
    call("practice summary", lambda: client.get("/api/v1/practice/summary", params={"target_id": tid}))
    call("resources", lambda: client.get("/api/v1/resources", params={"target_id": tid}))
    call("progress", lambda: client.get(f"/api/v1/targets/{tid}/progress"))
    call("me", lambda: client.get("/api/v1/auth/me"))
    print()
    for name, n in COUNTS.most_common():
        print(f"{n:5d}  {name}")
