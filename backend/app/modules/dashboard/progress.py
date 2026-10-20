"""Honest progress: deltas only between comparable measurements (SRS 9.6, FR-101)."""
from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import scoring_config as sc
from app.models import (Assessment, AssessmentItem, InterviewSession, InterviewTurn, ResumeAnalysis, Skill,
                        TargetRole, User)


def _items(db: Session, a: Assessment) -> list[AssessmentItem]:
    return db.scalars(select(AssessmentItem).where(AssessmentItem.assessment_id == a.id)).all()


def comparable(prev: Assessment, cur: Assessment, prev_items: list, cur_items: list) -> tuple[bool, str | None]:
    if prev.kind != "checkpoint" or cur.kind != "checkpoint":
        return False, "different test design (diagnostic vs checkpoint)"
    if prev.skill_id != cur.skill_id:
        return False, "different skill"
    if "abandoned" in (prev.status, cur.status):
        return False, "one attempt was not finished"
    if prev.scoring_version != cur.scoring_version:
        return False, "scoring method changed"
    if sorted(i.difficulty for i in prev_items) != sorted(i.difficulty for i in cur_items):
        return False, "different difficulty mix"
    tp, tc = Counter(i.type for i in prev_items), Counter(i.type for i in cur_items)
    if any(abs(tp.get(k, 0) - tc.get(k, 0)) > 1 for k in set(tp) | set(tc)):
        return False, "different question types"
    if prev.items_scored < sc.MIN_COMPARABLE_ITEMS or cur.items_scored < sc.MIN_COMPARABLE_ITEMS:
        return False, "too few scored questions"
    return True, None


def skill_series(db: Session, user: User, target: TargetRole) -> list[dict]:
    rows = db.scalars(select(Assessment).where(Assessment.user_id == user.id, Assessment.target_id == target.id,
                                               Assessment.status.in_(("scored", "scored_partial", "abandoned")))
                      .order_by(Assessment.scored_at)).all()
    from app.modules.catalog.cache import catalog
    skills = catalog(db).skills_by_id
    items_by_assessment: dict = {}
    if rows:
        for it in db.scalars(select(AssessmentItem).where(AssessmentItem.assessment_id.in_([a.id for a in rows]))):
            items_by_assessment.setdefault(it.assessment_id, []).append(it)
    series: dict = {}
    for a in rows:
        items = items_by_assessment.get(a.id, [])
        if a.kind == "diagnostic":
            by_skill: dict = {}
            for i in items:
                if i.score is None:
                    continue
                w = sc.DIFFICULTY_WEIGHT[i.difficulty]
                agg = by_skill.setdefault(i.skill_id, [0.0, 0.0, 0])
                agg[0] += w * float(i.score)
                agg[1] += w
                agg[2] += 1
            for sid, (ws, w, n) in by_skill.items():
                series.setdefault(sid, []).append({"assessment_id": str(a.id), "kind": "diagnostic",
                                                   "date": a.scored_at.isoformat() if a.scored_at else None,
                                                   "score": round(100 * ws / w), "items": n, "_a": a, "_i": items})
        else:
            series.setdefault(a.skill_id, []).append({"assessment_id": str(a.id), "kind": "checkpoint",
                                                      "date": a.scored_at.isoformat() if a.scored_at else None,
                                                      "score": round(float(a.score) * 100) if a.score is not None
                                                      else None, "items": a.items_scored,
                                                      "includes_repeats": bool(a.blueprint.get("includes_repeats")),
                                                      "_a": a, "_i": items})
    out = []
    for sid, pts in series.items():
        prev_cp = None
        for p in pts:
            p["comparable_with_previous"], p["reason"], p["delta"], p["change"] = False, None, None, None
            if p["kind"] == "checkpoint":
                if prev_cp is not None:
                    ok, reason = comparable(prev_cp["_a"], p["_a"], prev_cp["_i"], p["_i"])
                    p["comparable_with_previous"], p["reason"] = ok, reason
                    if ok and p["score"] is not None and prev_cp["score"] is not None:
                        d = p["score"] - prev_cp["score"]
                        p["delta"] = d
                        p["change"] = "No clear change" if abs(d) < sc.NO_CLEAR_CHANGE_DELTA else \
                            ("Improved" if d > 0 else "Declined")
                        overlap = {i.question_id for i in prev_cp["_i"]} & {i.question_id for i in p["_i"]}
                        if overlap:
                            p["includes_repeats"] = True
                else:
                    p["reason"] = "first checkpoint — take another to measure change"
                prev_cp = p
            else:
                p["reason"] = "diagnostic results are not compared with checkpoints (different test design)"
        for p in pts:
            p.pop("_a", None)
            p.pop("_i", None)
        s = skills.get(sid)
        out.append({"skill": {"slug": s.slug, "name": s.name} if s else None, "series": pts})
    out.sort(key=lambda x: x["skill"]["name"] if x["skill"] else "")
    return out


def interview_retries(db: Session, user: User, target: TargetRole) -> list[dict]:
    rows = db.execute(select(InterviewTurn, InterviewSession).join(InterviewSession, InterviewSession.id ==
                                                                   InterviewTurn.session_id)
                      .where(InterviewSession.target_id == target.id, InterviewTurn.user_id == user.id,
                             InterviewTurn.parent_turn_id.is_not(None), InterviewTurn.evaluation_status == "scored")
                      .order_by(InterviewTurn.answered_at.desc()).limit(20)).all()
    out = []
    for t, s in rows:
        prev = db.scalar(select(InterviewTurn).where(
            ((InterviewTurn.id == t.parent_turn_id) | (InterviewTurn.parent_turn_id == t.parent_turn_id)),
            InterviewTurn.attempt_number == t.attempt_number - 1))
        if prev is None or prev.evaluation_status != "scored":
            continue
        out.append({"question": t.question_text[:160], "date": t.answered_at.isoformat(), "attempt": t.attempt_number,
                    "previous_overall": prev.overall_score, "overall": t.overall_score,
                    "delta": t.overall_score - prev.overall_score, "rubric_version": s.rubric_version,
                    "note": "Same question, same rubric"})
    return out


def interview_trend(db: Session, user: User, target: TargetRole) -> list[dict]:
    rows = db.execute(select(InterviewTurn).join(InterviewSession, InterviewSession.id == InterviewTurn.session_id)
                      .where(InterviewSession.target_id == target.id, InterviewTurn.user_id == user.id,
                             InterviewTurn.evaluation_status == "scored")
                      .order_by(InterviewTurn.answered_at)).scalars().all()
    return [{"date": t.answered_at.isoformat(), "overall": t.overall_score, "question": t.question_text[:80],
             "attempt": t.attempt_number} for t in rows][-30:]


def coverage_history(db: Session, user: User, target: TargetRole) -> list[dict]:
    rows = db.scalars(select(ResumeAnalysis).where(ResumeAnalysis.user_id == user.id,
                                                   ResumeAnalysis.target_id == target.id)
                      .order_by(ResumeAnalysis.created_at)).all()
    out = []
    prev = None
    for a in rows[-20:]:
        item = {"date": a.created_at.isoformat(), "coverage": a.coverage_score, "resume_version_id":
                str(a.resume_version_id), "delta": None, "reason": None}
        if prev is not None:
            if prev.requirements_hash == a.requirements_hash:
                item["delta"] = a.coverage_score - prev.coverage_score
            else:
                item["reason"] = "requirements changed"
        prev = a
        out.append(item)
    return out
