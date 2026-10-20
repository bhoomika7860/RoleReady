from sqlalchemy import select

from app.ai.gateway import AIGateway
from app.ai.providers import FakeProvider
from app.core.config import get_settings
from app.models import Question, SkillEvidence
from app.modules.assessments.scoring import evaluate_short, score_objective
from app.modules.evidence.engine import SkillState, build_gaps, classify


def _answer_all(client, state, *, correct: bool, db):
    for item in state["items"]:
        q = db.get(Question, __import__("uuid").UUID(item["question_id"]))
        if item["type"] in ("short_answer", "approach"):
            resp = {"text": (q.reference_answer if correct else "I am not sure about this one at all honestly.")}
        else:
            right = q.correct_answer["selected"]
            wrong = [o["id"] for o in q.options if o["id"] not in right][:1]
            resp = {"selected": right if correct else wrong}
        r = client.put(f"/api/v1/assessments/{state['id']}/items/{item['position']}/response", json={"response": resp})
        assert r.status_code == 200, r.text


def test_objective_scoring_rules():
    assert score_objective("mcq_single", {"selected": ["b"]}, {"selected": ["b"]}) == 1.0
    assert score_objective("mcq_single", {"selected": ["b"]}, {"selected": ["a"]}) == 0.0
    assert score_objective("code_output", {"selected": ["c"]}, None) == 0.0
    # mcq_multi: max(0, (correct picked − wrong picked) / total correct)  (SRS T-096)
    assert score_objective("mcq_multi", {"selected": ["a", "b"]}, {"selected": ["a", "c"]}) == 0.0
    assert score_objective("mcq_multi", {"selected": ["a", "b", "c"]}, {"selected": ["a", "b"]}) == 2 / 3
    assert score_objective("mcq_multi", {"selected": ["a", "b"]}, {"selected": ["c", "d"]}) == 0.0


def test_short_answer_quotes_must_be_verbatim(db):
    q = db.scalar(select(Question).where(Question.slug == "sql-m-sa1"))
    answer = "INNER JOIN keeps only matching rows. A LEFT JOIN keeps all rows from the left table with NULLs."

    def judge(system, user):
        return {"key_points": [{"id": "kp1", "credit": "covered", "quote": "INNER JOIN keeps only matching rows"},
                               {"id": "kp2", "credit": "covered", "quote": "LEFT JOIN returns everything ever"},
                               {"id": "kp3", "credit": "partial", "quote": None}],
                "feedback": "ok", "notes": []}
    gw = AIGateway(FakeProvider(handlers={"W-7": judge}), get_settings())
    out = evaluate_short(gw, q, answer, None, "Backend Developer")
    points = {p["id"]: p for p in out["evaluation"]["key_points"]}
    assert points["kp1"]["credit"] == "covered" and points["kp1"]["quote_verified"]
    assert points["kp2"]["credit"] == "missing"  # fabricated quote → no credit
    assert points["kp3"]["credit"] == "missing"  # credit without a quote → no credit
    assert out["score"] == 0.35


def test_short_answer_too_short_is_scored_without_ai(db):
    q = db.scalar(select(Question).where(Question.slug == "sql-m-sa1"))
    gw = AIGateway(FakeProvider(handlers={}), get_settings())
    out = evaluate_short(gw, q, "joins differ", None, "x")
    assert out["score"] == 0.0 and out["evaluation"]["method"] == "deterministic"


def test_diagnostic_blueprint_and_no_answer_leak(client, target, db):
    r = client.post(f"/api/v1/targets/{target['id']}/assessments", json={"kind": "diagnostic"})
    assert r.status_code == 201
    state = r.json()
    assert len(state["items"]) == 15
    raw = r.text
    assert "correct_answer" not in raw and "reference_answer" not in raw and "explanation" not in raw
    shorts = [i for i in state["items"] if i["type"] in ("short_answer", "approach")]
    assert len(shorts) == 3
    ps = [i for i in state["items"] if i["type"] in ("code_output", "approach")]
    assert len(ps) >= 3
    skills = [i["skill"]["slug"] for i in state["items"]]
    assert skills.count("python") == 3 and skills.count("sql") == 3 and skills.count("rest-api") == 3
    # starting again returns the same in-progress attempt
    again = client.post(f"/api/v1/targets/{target['id']}/assessments", json={"kind": "diagnostic"}).json()
    assert again["id"] == state["id"]


def test_autosave_resume_submit_and_double_submit(client, target, db):
    state = client.post(f"/api/v1/targets/{target['id']}/assessments", json={"kind": "diagnostic"}).json()
    first = state["items"][0]
    q = db.get(Question, __import__("uuid").UUID(first["question_id"]))
    resp = {"selected": q.correct_answer["selected"]} if q.options else {"text": "x"}
    client.put(f"/api/v1/assessments/{state['id']}/items/1/response", json={"response": resp})
    reloaded = client.get(f"/api/v1/assessments/{state['id']}").json()
    assert reloaded["items"][0]["response"] == resp and reloaded["first_unanswered"] == 2
    _answer_all(client, reloaded, correct=True, db=db)
    sub = client.post(f"/api/v1/assessments/{state['id']}/submit")
    assert sub.status_code == 200 and sub.json()["status"] == "scored"
    assert sub.json()["score"] >= 90
    dup = client.post(f"/api/v1/assessments/{state['id']}/submit")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "ASSESSMENT_CLOSED"
    n_evidence = len(db.scalars(select(SkillEvidence).where(SkillEvidence.source_type == "assessment")).all())
    assert n_evidence == 15
    result = client.get(f"/api/v1/assessments/{state['id']}/result").json()
    assert all("correct_answer" in i for i in result["items"]) and result["skills"]


def test_failed_ai_evaluation_is_never_zero(client, target, db, fake_ai):
    from app.ai.providers import ProviderError
    fake_ai.handlers["W-7"] = lambda s, u: ProviderError("server_error", 503, "down")
    state = client.post(f"/api/v1/targets/{target['id']}/assessments", json={"kind": "diagnostic"}).json()
    _answer_all(client, state, correct=True, db=db)
    sub = client.post(f"/api/v1/assessments/{state['id']}/submit").json()
    assert sub["status"] == "scored_partial" and sub["items_scored"] == 12
    result = client.get(f"/api/v1/assessments/{state['id']}/result").json()
    failed = [i for i in result["items"] if i["evaluation_status"] == "failed"]
    assert len(failed) == 3 and all(i["score"] is None for i in failed)
    assert sub["score"] >= 90  # failed items are excluded, not counted as 0
    # retry once the provider is back
    from tests.conftest import default_w7
    fake_ai.handlers["W-7"] = default_w7
    pos = failed[0]["position"]
    r = client.post(f"/api/v1/assessments/{state['id']}/items/{pos}/retry-evaluation")
    assert r.status_code == 200 and r.json()["evaluation_status"] == "scored"


def _state(name, imp, R, D, n):
    return SkillState(skill_id=name, slug=name, name=name.upper(), importance=imp, R=R, D=D, n=n,
                      confidence="medium")


def test_gap_rules_and_priority_formula():
    # SRS worked example: SQL core, R=1, D=0.33, n=3 → G3, S=0.87, C=0.90 → P=78
    gaps = build_gaps([_state("sql", "core", 1, 0.33, 3)], True, "Backend Developer", {}, {})
    g = gaps[0]
    assert g["type"] == "G3" and g["priority"] == 78
    assert g["inputs"]["S"] == 0.868 and g["inputs"]["C"] == 0.9
    # DSA required, R=1, D=0.40, n=2 → G2 S=0.43 C=0.8 → 26
    assert build_gaps([_state("dsa", "required", 1, 0.40, 2)], True, "x", {}, {})[0]["priority"] == 26
    # Docker preferred, not on resume, never assessed → G1 S=0.6 C=0.7 → 17
    docker = build_gaps([_state("docker", "preferred", 0, None, 0)], True, "x", {}, {})[0]
    assert docker["type"] == "G1" and docker["priority"] == 17
    assert docker["next_action"]["type"] == "reassess"  # absence from resume → measure, not "learn"


def test_resume_absence_alone_never_means_weak():
    assert classify(_state("x", "core", 0, None, 0), True)[0] == "G1"
    assert classify(_state("x", "core", None, None, 0), False)[0] == "G5"   # no resume → never G1/G4
    assert classify(_state("x", "core", None, 0.9, 5), False) is None
    assert classify(_state("x", "core", 0, 0.9, 5), True)[0] == "G4"
    assert classify(_state("x", "core", 3, 0.9, 5), True) is None


def test_prerequisite_adjustments():
    states = [_state("http", "required", 1, 0.2, 4), _state("rest", "core", 1, 0.3, 4)]
    gaps = {g["skill"]["slug"]: g for g in build_gaps(states, True, "x", {"rest": {"http"}}, {})}
    assert gaps["http"]["inputs"]["B_prereq"] == 10
    assert gaps["rest"]["next_action"]["skill"] == "http" and "Strengthen" in gaps["rest"]["next_action"]["label"]


def test_gap_report_after_diagnostic_and_readiness(client, target, db):
    state = client.post(f"/api/v1/targets/{target['id']}/assessments", json={"kind": "diagnostic"}).json()
    _answer_all(client, state, correct=False, db=db)
    client.post(f"/api/v1/assessments/{state['id']}/submit")
    rep = client.get(f"/api/v1/targets/{target['id']}/gap-reports/latest").json()
    assert rep["gaps"] and all({"I", "S", "C", "n"} <= set(g["inputs"]) for g in rep["gaps"])
    weak = [g for g in rep["gaps"] if g["type"] == "G2"]
    assert weak, rep["gaps"][:3]
    readiness = client.get(f"/api/v1/targets/{target['id']}/readiness").json()
    assert readiness["dimensions"]["TK"]["score"] is not None
    assert readiness["dimensions"]["IC"]["score"] is None  # no interviews → no number, never 0
    assert readiness["index"] is None  # needs ≥ 3 medium-confidence dimensions


def test_checkpoint_comparability(client, target, db):
    def run_checkpoint(correct):
        st = client.post(f"/api/v1/targets/{target['id']}/assessments",
                         json={"kind": "checkpoint", "skill_slug": "sql"}).json()
        assert len(st["items"]) == 6
        _answer_all(client, st, correct=correct, db=db)
        client.post(f"/api/v1/assessments/{st['id']}/submit")
        return st
    first = run_checkpoint(False)
    second = run_checkpoint(True)
    assert first["blueprint"]["difficulty_mix"] == second["blueprint"]["difficulty_mix"]
    prog = client.get(f"/api/v1/targets/{target['id']}/progress").json()
    sql = next(s for s in prog["skills"] if s["skill"]["slug"] == "sql")
    cps = [p for p in sql["series"] if p["kind"] == "checkpoint"]
    assert cps[1]["comparable_with_previous"] is True and cps[1]["delta"] > 17
    assert cps[1]["change"] == "Improved"
    bad = client.post(f"/api/v1/targets/{target['id']}/assessments", json={"kind": "checkpoint",
                                                                          "skill_slug": "excel"})
    assert bad.status_code == 422  # not one of this target's requirements
