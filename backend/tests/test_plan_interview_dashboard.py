import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select, update

from app.models import InterviewTurn, PreparationPlan, PreparationTask, Question
from app.modules.plans.planner import GapInput, Resource, build_plan
from tests.conftest import default_w7
from tests.test_assessment_and_gaps import _answer_all
from tests.test_isolation import RESUME_TEXT

TODAY = date(2026, 10, 20)


def _gaps():
    return [GapInput("G3", 78, "s1", "sql", "SQL", "core", 0.33, 3),
            GapInput("G2", 60, "s2", "dsa", "Data structures", "required", 0.4, 2),
            GapInput("G2", 50, "s3", "http", "HTTP", "required", 0.3, 4),
            GapInput("G1", 17, "s4", "docker", "Docker", "preferred", None, 0),
            GapInput("G6", 30, None, None, None, "interview", None, 3, interview_dimension="reasoning")]


def test_plan_respects_daily_minutes_and_ordering():
    res = {"s2": Resource("r1", "DSA intro", 30), "s3": Resource("r2", "HTTP overview", 20)}
    plan = build_plan(_gaps(), TODAY, TODAY + timedelta(days=10), 60, set(), res, has_diagnostic=True)
    for day, tasks in plan.days:
        assert sum(t.minutes for t in tasks) <= 60
        assert len({t.skill_slug or t.interview_dimension for t in tasks}) <= 2
    by_seq = defaultdict(list)
    for day, tasks in plan.days:
        for t in tasks:
            by_seq[t.seq_key].append((t.step_index, day, t.task_type))
    for seq, steps in by_seq.items():
        steps.sort()
        for (i, d, typ), (j, d2, typ2) in zip(steps, steps[1:]):
            assert d2 >= d
            if typ2 == "reassess":
                assert d2 > d, f"re-check must be at least a day after practice in {seq}"
    # deterministic
    again = build_plan(_gaps(), TODAY, TODAY + timedelta(days=10), 60, set(), res, has_diagnostic=True)
    assert [(d, [t.title for t in ts]) for d, ts in plan.days] == [(d, [t.title for t in ts]) for d, ts in again.days]


def test_tight_deadline_lists_unscheduled_work_instead_of_overflowing():
    plan = build_plan(_gaps(), TODAY, TODAY + timedelta(days=3), 30, set(), {}, has_diagnostic=False)
    total = sum(t.minutes for _, ts in plan.days for t in ts)
    assert total <= 3 * 30
    assert plan.unscheduled, "lower-priority gaps must be listed, not silently dropped"
    first_day_titles = [t.title for t in plan.days[0][1]]
    assert first_day_titles[0].startswith("Take your diagnostic")


def test_completed_steps_are_not_rescheduled():
    plan = build_plan(_gaps()[:1], TODAY, TODAY + timedelta(days=10), 60, {("sql:G3", 0), ("sql:G3", 1)}, {},
                      has_diagnostic=True)
    types = [t.task_type for _, ts in plan.days for t in ts]
    assert types == ["reassess"]


def test_plan_api_rollover_and_task_rules(client, target, db):
    plan = client.post(f"/api/v1/targets/{target['id']}/plans")
    assert plan.status_code == 201
    body = plan.json()
    first = body["days"][0]["tasks"][0]
    assert first["type"] == "assess" and first["auto_completes"]
    r = client.patch(f"/api/v1/plan-tasks/{first['id']}", json={"status": "done"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TASK_AUTO_COMPLETES"
    assert client.patch(f"/api/v1/plan-tasks/{first['id']}", json={"status": "skipped"}).status_code == 200
    # simulate two missed days: move pending tasks into the past and reset the rollover marker
    pid = uuid.UUID(body["plan_id"])
    db.execute(update(PreparationTask).where(PreparationTask.plan_id == pid, PreparationTask.status == "pending")
               .values(scheduled_date=date.today() - timedelta(days=2)))
    db.execute(update(PreparationPlan).where(PreparationPlan.id == pid).values(last_rollover_date=None))
    db.commit()
    rolled = client.get(f"/api/v1/targets/{target['id']}/plans/active").json()
    assert rolled["banner"] and rolled["revision"] == 2
    assert all(d["total_minutes"] <= 60 for d in rolled["days"])
    assert any(t["status"] == "missed" for t in rolled["history"])


def test_diagnostic_completion_ticks_plan_task_and_changes_next_action(client, target, db):
    reqs = client.get(f"/api/v1/targets/{target['id']}/requirements").json()
    items = [{"id": x["id"], "skill_slug": x["skill"]["slug"], "requirement_level": x["requirement_level"]}
             for x in reqs["requirements"]]
    client.put(f"/api/v1/targets/{target['id']}/requirements", json={"requirements": items})
    na = client.get(f"/api/v1/targets/{target['id']}/recommendations/next").json()
    assert na["primary"]["action_type"] == "take_diagnostic"
    client.post(f"/api/v1/targets/{target['id']}/plans")
    st = client.post(f"/api/v1/targets/{target['id']}/assessments", json={"kind": "diagnostic"}).json()
    na = client.get(f"/api/v1/targets/{target['id']}/recommendations/next").json()
    assert na["primary"]["action_type"] == "resume_assessment"
    _answer_all(client, st, correct=False, db=db)
    client.post(f"/api/v1/assessments/{st['id']}/submit")
    assess_task = db.scalar(select(PreparationTask).where(PreparationTask.task_type == "assess"))
    assert assess_task is None or assess_task.status == "done"
    na = client.get(f"/api/v1/targets/{target['id']}/recommendations/next").json()
    assert na["mode"] == "evidence" and na["primary"]["action_type"] in ("learn", "practice", "reassess", "add_resume")
    assert na["primary"]["why"] and na["primary"]["score_breakdown"]["rule"]
    assert len(na["alternatives"]) <= 3


def test_onboarding_ladder_for_new_user(login, fake_ai):
    c = login("newbie@example.com")
    dash = c.get("/api/v1/dashboard").json()
    assert dash["target"] is None and dash["next_action"]["primary"]["action_type"] == "set_target"
    t = c.post("/api/v1/targets", json={"role_slug": "data-analyst", "daily_minutes": 45}).json()["target"]
    d = c.get(f"/api/v1/targets/{t['id']}/dashboard").json()
    assert d["next_action"]["primary"]["action_type"] == "confirm_requirements"
    assert d["readiness"]["index"] is None and d["coverage"]["status"] == "empty"
    assert d["readiness"]["dimensions"]["TK"]["score"] is None  # no fabricated numbers for new users
    assert d["latest_assessment"]["status"] == "empty" and d["interview"]["status"] == "empty"


def test_practice_scores_and_writes_evidence(client, target, db):
    qs = client.get("/api/v1/practice/questions", params={"target_id": target["id"], "skill": "sql"}).json()
    assert len(qs["items"]) == 5 and "correct_answer" not in str(qs)
    obj = next(i for i in qs["items"] if i["type"] in ("mcq_single", "code_output"))
    q = db.get(Question, uuid.UUID(obj["question_id"]))
    r = client.post("/api/v1/practice/attempts", json={"question_id": obj["question_id"], "target_id": target["id"],
                                                       "response": {"selected": q.correct_answer["selected"]}})
    assert r.status_code == 201 and r.json()["correct"] is True and r.json()["explanation"]
    assert r.json()["feedback_kind"] == "deterministic"


def test_practice_failed_ai_writes_no_evidence(client, target, db, fake_ai):
    from app.ai.providers import ProviderError
    from app.models import SkillEvidence
    fake_ai.handlers["W-7"] = lambda s, u: ProviderError("timeout")
    q = db.scalar(select(Question).where(Question.slug == "sql-m-sa1"))
    r = client.post("/api/v1/practice/attempts", json={"question_id": str(q.id), "target_id": target["id"],
                                                       "response": {"text": "LEFT JOIN keeps all rows from the "
                                                                            "left table and fills NULLs."}})
    assert r.status_code == 201 and r.json()["evaluation_status"] == "failed" and r.json()["score"] is None
    assert r.json()["reference_answer"]
    assert db.scalar(select(SkillEvidence).where(SkillEvidence.source_type == "practice")) is None


# ------------------------------------------------------------------ interviews
ANSWER = ("A LEFT JOIN keeps every row from the left table and fills the right side with NULL when there is no "
          "match, while an INNER JOIN keeps only matching rows, so customers without orders disappear.")


def test_interview_score_is_computed_in_code_and_quotes_checked(client, target, fake_ai):
    def judge(system, user):
        out = default_w7(system, user)
        out["dimensions"]["clarity"] = {"score": 5, "quote": "words that never appeared", "comment": "x"}
        out["dimensions"]["reasoning"] = {"score": 1, "quote": None, "comment": "no reasoning"}
        return out
    fake_ai.handlers["W-7"] = judge
    s = client.post(f"/api/v1/targets/{target['id']}/interviews", json={"type": "technical", "skill_slug": "sql"})
    assert s.status_code == 201
    turn = s.json()["turns"][0]
    assert turn["source_label"].startswith("Curated")
    r = client.post(f"/api/v1/interviews/{s.json()['id']}/turns/{turn['id']}/answer",
                    json={"answer_text": ANSWER, "input_mode": "typed"})
    assert r.status_code == 200, r.text
    t = r.json()
    scores = {k: v["score"] for k, v in t["rubric_scores"].items()}
    assert scores["clarity"] == 2 and t["rubric_scores"]["clarity"]["quote"] is None  # unverifiable → capped
    assert scores["reasoning"] == 1
    assert t["overall_score"] == round(sum(scores.values()) / 5 * 20)
    assert "tone" in t["disclaimer"]


def test_interview_answer_persists_when_ai_fails_and_retry_works(client, target, fake_ai, db):
    from app.ai.providers import ProviderError
    fake_ai.handlers["W-7"] = lambda s, u: ProviderError("server_error", 502, "bad gateway")
    s = client.post(f"/api/v1/targets/{target['id']}/interviews", json={"type": "technical"}).json()
    turn = s["turns"][0]
    r = client.post(f"/api/v1/interviews/{s['id']}/turns/{turn['id']}/answer", json={"answer_text": ANSWER})
    assert r.status_code == 200 and r.json()["evaluation_status"] == "failed"
    assert r.json()["overall_score"] is None and r.json()["answer_text"] == ANSWER
    stored = db.get(InterviewTurn, uuid.UUID(turn["id"]))
    assert stored.answer_text == ANSWER and stored.overall_score is None
    again = client.post(f"/api/v1/interviews/{s['id']}/turns/{turn['id']}/answer", json={"answer_text": ANSWER})
    assert again.status_code == 409
    fake_ai.handlers["W-7"] = default_w7
    ev = client.post(f"/api/v1/interviews/{s['id']}/turns/{turn['id']}/evaluate")
    assert ev.status_code == 200 and ev.json()["evaluation_status"] == "scored"
    # retry the same question → comparable delta
    retry = client.post(f"/api/v1/interviews/{s['id']}/turns/{turn['id']}/retry")
    assert retry.status_code == 201 and retry.json()["attempt_number"] == 2
    t2 = client.post(f"/api/v1/interviews/{s['id']}/turns/{retry.json()['id']}/answer",
                     json={"answer_text": ANSWER + " It matters for reports of inactive customers."}).json()
    assert t2["delta"] is not None and t2["delta"]["comparable"] is True


def test_project_interview_uses_resume_entry(client, target):
    no = client.post(f"/api/v1/targets/{target['id']}/interviews", json={"type": "project"})
    assert no.status_code == 422 and no.json()["error"]["code"] == "NO_PROJECTS_ON_RESUME"
    client.post("/api/v1/resumes/from-text", json={"text": RESUME_TEXT})
    s = client.post(f"/api/v1/targets/{target['id']}/interviews", json={"type": "project"}).json()
    q = s["turns"][0]
    assert "Campus Events API" in q["question_text"] and q["source_label"] == "Built from your resume"


def test_too_short_interview_answer_is_not_scored(client, target):
    s = client.post(f"/api/v1/targets/{target['id']}/interviews", json={"type": "technical"}).json()
    r = client.post(f"/api/v1/interviews/{s['id']}/turns/{s['turns'][0]['id']}/answer",
                    json={"answer_text": "It joins two tables together."})
    assert r.json()["evaluation_status"] == "too_short" and r.json()["overall_score"] is None
