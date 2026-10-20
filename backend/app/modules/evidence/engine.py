"""Evidence → skill states → gaps → readiness. Pure, deterministic code (SRS FR-050–052, Section 9).

Priority formula (SRS 5.5):  P = min(100, round(100 × I × S × C) + B_prereq)
  I  importance of the skill to the target job: core 1.0, required 0.75, preferred 0.40 (interview 0.80)
  S  severity of the gap, 0–1, defined per gap type below (how far demonstrated ability is from adequate)
  C  confidence multiplier from evidence count n: 0 → 0.70, 1–2 → 0.80, 3–5 → 0.90, ≥6 → 1.00
  B  +10 if this skill is a prerequisite of a skill with an open weak/at-risk gap
A skill whose own prerequisite is weak has P × 0.6 and its action becomes "strengthen the prerequisite first".
Deadline urgency is handled by the planner (it fits the highest-P work into the days that remain).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import scoring_config as sc
from app.models import (GapReport, InterviewTurn, Question, Resume, ResumeAnalysis, Role, SkillEvidence, SkillGap,
                        SkillPrerequisite, TargetRole, User)
from app.modules.targets.requirements import Req, load_requirements, requirements_hash


@dataclass
class SkillState:
    skill_id: str
    slug: str
    name: str
    importance: str
    R: int | None            # resume evidence level 0–3, None when no resume analysis exists
    D: float | None          # demonstrated score 0–1, None when n = 0
    n: int                   # scored evidence items in the window
    confidence: str          # none | low | medium | high
    sources: dict = field(default_factory=dict)
    last_evidence_at: str | None = None
    resume_state: str = "no_resume"        # evidenced | weak | not_shown | no_resume
    demonstrated_state: str = "not_assessed"  # not_assessed | demonstrated | developing | weak
    demonstrated_source: str | None = None    # assessment | practice | interview


def _skill_confidence(n: int) -> str:
    return "none" if n == 0 else "low" if n <= 2 else "medium" if n <= 5 else "high"


_UNSET = object()


def latest_analysis(db: Session, user_id, target_id) -> ResumeAnalysis | None:
    """Latest analysis of the user's primary (most recently updated) resume for this target — one query."""
    primary = select(Resume.id).where(Resume.user_id == user_id).order_by(Resume.updated_at.desc()).limit(1) \
        .scalar_subquery()
    return db.scalar(select(ResumeAnalysis).where(ResumeAnalysis.target_id == target_id,
                                                  ResumeAnalysis.resume_id == primary)
                     .order_by(ResumeAnalysis.created_at.desc()).limit(1))


def primary_resume(db: Session, user_id) -> Resume | None:
    return db.scalar(select(Resume).where(Resume.user_id == user_id).order_by(Resume.updated_at.desc()).limit(1))


def compute_states(db: Session, user: User, target: TargetRole, reqs: list[Req] | None = None,
                   analysis=_UNSET) -> list[SkillState]:
    reqs = reqs if reqs is not None else load_requirements(db, target, scored_only=True)
    if analysis is _UNSET:
        analysis = latest_analysis(db, user.id, target.id)
    levels: dict[str, int] = {}
    if analysis:
        for row in analysis.result.get("requirements", []):
            if row.get("skill"):
                levels[row["skill"]["slug"]] = row["level"]
    has_resume = analysis is not None
    skill_ids = [r.skill_id for r in reqs if r.skill_id]
    ev_by_skill: dict[uuid.UUID, list[SkillEvidence]] = defaultdict(list)
    if skill_ids:
        rows = db.scalars(select(SkillEvidence).where(
            SkillEvidence.user_id == user.id, SkillEvidence.skill_id.in_(skill_ids),
            SkillEvidence.source_type.in_(("assessment", "practice", "interview")),
            SkillEvidence.score.is_not(None)).order_by(SkillEvidence.observed_at.desc())).all()
        for ev in rows:
            if len(ev_by_skill[ev.skill_id]) < sc.EVIDENCE_WINDOW:
                ev_by_skill[ev.skill_id].append(ev)
    states = []
    for r in reqs:
        if not r.skill_id:
            continue
        evs = ev_by_skill.get(r.skill_id, [])
        n = len(evs)
        D = None
        if n:
            wsum = sum(float(e.difficulty_weight) for e in evs)
            D = sum(float(e.difficulty_weight) * float(e.score) for e in evs) / wsum
        R = levels.get(r.skill_slug) if has_resume else None
        sources: dict[str, int] = defaultdict(int)
        for e in evs:
            sources[e.source_type] += 1
        resume_state = "no_resume" if R is None else sc.EVIDENCE_LEVEL_STATE[R]
        if D is None:
            dem = "not_assessed"
        elif D >= 0.70:
            dem = "demonstrated"
        elif D >= 0.50:
            dem = "developing"
        else:
            dem = "weak"
        dem_source = max(sources, key=lambda k: sources[k]) if sources else None
        states.append(SkillState(str(r.skill_id), r.skill_slug or "", r.skill_name or r.raw_phrase, r.importance,
                                 R, round(D, 3) if D is not None else None, n, _skill_confidence(n), dict(sources),
                                 evs[0].observed_at.isoformat() if evs else None, resume_state, dem, dem_source))
    return states


# ------------------------------------------------------------------ gap rules (first match wins)
def classify(s: SkillState, has_resume: bool) -> tuple[str, float] | None:
    R, D, n = s.R, s.D, s.n
    if D is not None and R is not None and D >= sc.NO_GAP_D and R >= sc.NO_GAP_R:
        return None
    if R is not None and R >= 1 and n >= 3 and D is not None and D < 0.50:
        return "G3", min(1.0, 0.8 + 0.4 * (0.5 - D))
    if n >= 2 and D is not None and D < 0.60:
        return "G2", max(0.15, min(1.0, (0.70 - D) / 0.70))
    if has_resume and n >= 3 and D is not None and D >= 0.75 and (R or 0) <= 1:
        return "G4", 0.40
    if n == 0 and (not has_resume or (R or 0) >= 1):
        return "G5", 0.50
    if n == 0 and has_resume and (R or 0) == 0:
        return "G1", 0.60
    return None


NEXT_ACTION = {
    "G1": ("reassess", "Take a 6-question checkpoint first"),
    "G2": ("learn", "Learn, then practise, then re-check"),
    "G3": ("practice", "Practise, then take a checkpoint"),
    "G4": ("improve_resume", "Add evidence to your resume"),
    "G5": ("reassess", "Take a 6-question checkpoint"),
    "G6": ("interview", "Do a mock interview focused on this"),
}


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{round(x * 100)}%"


def explain(gap_type: str, s: SkillState | None, role_name: str, dim: str | None = None,
            dim_mean: float | None = None, k: int = 0) -> str:
    if gap_type == "G6":
        return (f"Your recent interview answers averaged {dim_mean:.1f}/5 on {dim} over the last {k} answers. "
                f"A mock interview focused on {dim} is the most direct way to improve it.")
    assert s is not None
    imp = f"a {s.importance} requirement for {role_name}"
    if gap_type == "G3":
        return (f"{s.name} is {imp}. Your resume lists it, but your recent answers averaged {_pct(s.D)} over "
                f"{s.n} questions. Interviewers often test skills you list. Next: practise {s.name}, then take a "
                f"checkpoint.")
    if gap_type == "G2":
        return (f"{s.name} is {imp}. Your recent answers averaged {_pct(s.D)} over {s.n} questions. "
                f"Next: review it, practise, then re-check with a checkpoint.")
    if gap_type == "G4":
        return (f"You've shown strong {s.name} ({_pct(s.D)} over {s.n} questions), but your resume doesn't show it "
                f"being used. If you have used it in a project or internship, add it there.")
    if gap_type == "G5":
        return (f"{s.name} is {imp} and hasn't been assessed yet, so there's no evidence either way. "
                f"A short checkpoint will show where you stand.")
    return (f"{s.name} is {imp}. It isn't shown on your resume and hasn't been assessed — that is not evidence that "
            f"you can't do it. Take a checkpoint first to find out.")


def deep_link(action: str, slug: str | None, dim: str | None = None) -> str:
    if action in ("reassess",):
        return f"/app/assessment?checkpoint={slug}"
    if action == "practice":
        return f"/app/practice?skill={slug}"
    if action == "learn":
        return f"/app/resources?skill={slug}"
    if action == "improve_resume":
        return "/app/resume?tab=match"
    if action == "interview":
        return f"/app/interview?focus={dim}" if dim else "/app/interview"
    return "/app/dashboard"


def interview_dimension_means(db: Session, user_id) -> dict[str, tuple[float, int, int]]:
    """dimension -> (mean of last 3 scores on 1–5 scale, last-3 count, total evaluated)."""
    rows = db.execute(select(SkillEvidence.interview_dimension, SkillEvidence.score).where(
        SkillEvidence.user_id == user_id, SkillEvidence.interview_dimension.is_not(None),
        SkillEvidence.score.is_not(None)).order_by(SkillEvidence.observed_at.desc()).limit(500)).all()
    by_dim: dict[str, list[float]] = defaultdict(list)
    for dim, score in rows:
        by_dim[dim].append(float(score) * 5)
    return {dim: (sum(v[:3]) / len(v[:3]), len(v[:3]), len(v)) for dim, v in by_dim.items()}


def prerequisites(db: Session) -> dict[str, set[str]]:
    from app.modules.catalog.cache import catalog
    return catalog(db).prerequisites


def build_gaps(states: list[SkillState], has_resume: bool, role_name: str, prereq: dict[str, set[str]],
               dims: dict[str, tuple[float, int, int]]) -> list[dict]:
    by_id = {s.skill_id: s for s in states}
    raw = []
    for s in states:
        c = classify(s, has_resume)
        if c:
            raw.append((s, c[0], c[1]))
    weak_ids = {s.skill_id for s, t, _ in raw if t in ("G2", "G3")}
    gaps = []
    for s, gtype, sev in raw:
        imp = sc.IMPORTANCE_WEIGHT[s.importance]
        conf = sc.confidence_multiplier(s.n)
        base = round(100 * imp * sev * conf)
        bonus = sc.PREREQ_BONUS if any(s.skill_id in prereq.get(other, set()) for other in weak_ids) else 0
        weak_prereqs = [by_id[p] for p in prereq.get(s.skill_id, set()) if p in weak_ids and p in by_id]
        priority = min(100, base + bonus)
        action, action_label = NEXT_ACTION[gtype]
        adjustments = []
        if bonus:
            adjustments.append("+10: other weak skills build on this one")
        target_slug = s.slug
        if weak_prereqs:
            priority = round(priority * sc.PREREQ_PENALTY)
            p = sorted(weak_prereqs, key=lambda x: x.name)[0]
            action, action_label, target_slug = "practice", f"Strengthen {p.name} first", p.slug
            adjustments.append(f"×0.6: its prerequisite {p.name} is still weak")
        gaps.append({
            "type": gtype, "label": sc.GAP_LABELS[gtype], "skill_id": s.skill_id, "skill": {"slug": s.slug,
                                                                                            "name": s.name},
            "interview_dimension": None, "importance": s.importance, "priority": priority,
            "inputs": {"I": imp, "S": round(sev, 3), "C": conf, "R": s.R, "D": s.D, "n": s.n, "B_prereq": bonus},
            "adjustments": adjustments, "explanation": explain(gtype, s, role_name),
            "next_action": {"type": action, "label": action_label, "skill": target_slug,
                            "deep_link": deep_link(action, target_slug)},
            "resume_state": s.resume_state, "demonstrated_state": s.demonstrated_state})
    for dim, (mean, k, total) in dims.items():
        if total >= 2 and mean < 3.0:
            sev = max(0.0, min(1.0, (3.5 - mean) / 3.5))
            conf = sc.confidence_multiplier(total)
            priority = min(100, round(100 * sc.INTERVIEW_GAP_IMPORTANCE * sev * conf))
            gaps.append({
                "type": "G6", "label": sc.GAP_LABELS["G6"], "skill_id": None, "skill": None,
                "interview_dimension": dim, "importance": "interview", "priority": priority,
                "inputs": {"I": sc.INTERVIEW_GAP_IMPORTANCE, "S": round(sev, 3), "C": conf, "mean_last_3": round(mean, 2),
                           "n": total}, "adjustments": [], "explanation": explain("G6", None, role_name, dim, mean, k),
                "next_action": {"type": "interview", "label": NEXT_ACTION["G6"][1], "skill": None, "dimension": dim,
                                "deep_link": deep_link("interview", None, dim)},
                "resume_state": None, "demonstrated_state": None})
    order = {"core": 0, "required": 1, "interview": 1, "preferred": 2}
    gaps.sort(key=lambda g: (-g["priority"], order.get(g["importance"], 3),
                             (g["skill"] or {}).get("name") or g["interview_dimension"] or ""))
    for i, g in enumerate(gaps, 1):
        g["rank"] = i
    return gaps


# ------------------------------------------------------------------ readiness (SRS 9.2–9.4)
def _band(score: int) -> str:
    for threshold, name in sc.READINESS_BANDS:
        if score >= threshold:
            return name
    return "Early"


def readiness(db: Session, user: User, target: TargetRole, states: list[SkillState],
              analysis=_UNSET) -> tuple[dict, dict | None]:
    from app.modules.catalog.cache import catalog
    role = catalog(db).roles_by_id[target.role_id]
    weights = {k: v["weight"] for k, v in role.dimension_config["dimensions"].items() if v.get("applies")}
    if analysis is _UNSET:
        analysis = latest_analysis(db, user.id, target.id)
    dims: dict[str, dict] = {}

    # RA and PE — resume-only
    if analysis is None:
        dims["RA"] = {"score": None, "confidence": "none", "basis": "No resume analysed yet"}
        dims["PE"] = {"score": None, "confidence": "none", "basis": "No resume analysed yet"}
    else:
        reviewed = db.scalar(select(Resume.reviewed_at).where(Resume.id == analysis.resume_id)) is not None
        confirmed = target.requirements_confirmed_at is not None
        conf = "high" if reviewed and confirmed else "medium"
        basis = "Requirement coverage of your current resume" + ("" if confirmed else " (requirements not confirmed)")
        dims["RA"] = {"score": analysis.coverage_score, "confidence": conf, "basis": basis}
        dims["PE"] = {"score": analysis.pe_score, "confidence": conf,
                      "basis": "Projects/experience that show core skills in use, plus measured outcomes"}

    # TK — demonstrated only
    total_i = sum(sc.IMPORTANCE_WEIGHT[s.importance] for s in states)
    assessed = [s for s in states if s.n >= 1 and s.D is not None]
    m = sum(s.n for s in assessed)
    if assessed:
        tk = round(100 * sum(sc.IMPORTANCE_WEIGHT[s.importance] * s.D for s in assessed) /
                   sum(sc.IMPORTANCE_WEIGHT[s.importance] for s in assessed))
        a = sum(sc.IMPORTANCE_WEIGHT[s.importance] for s in assessed) / total_i if total_i else 0
        conf = "high" if a >= 0.7 and m >= 12 else "medium" if a >= 0.4 and m >= 6 else "low"
        dims["TK"] = {"score": tk, "confidence": conf,
                      "basis": f"Based on {m} answers across {len(assessed)} of {len(states)} required skills"}
    else:
        dims["TK"] = {"score": None, "confidence": "none", "basis": "No skills assessed yet"}

    # PS — code-output and approach items
    skill_ids = [uuid.UUID(s.skill_id) for s in states]
    ps_rows = db.execute(select(SkillEvidence.score, SkillEvidence.difficulty_weight).where(
        SkillEvidence.user_id == user.id, SkillEvidence.skill_id.in_(skill_ids) if skill_ids else False,
        SkillEvidence.item_type.in_(("code_output", "approach")), SkillEvidence.score.is_not(None))
        .order_by(SkillEvidence.observed_at.desc()).limit(12)).all() if skill_ids else []
    if ps_rows:
        w = sum(float(r.difficulty_weight) for r in ps_rows)
        ps = round(100 * sum(float(r.score) * float(r.difficulty_weight) for r in ps_rows) / w)
        k = len(ps_rows)
        dims["PS"] = {"score": ps, "confidence": "high" if k >= 8 else "medium" if k >= 4 else "low",
                      "basis": f"Based on {k} code-reasoning and approach questions"}
    else:
        dims["PS"] = {"score": None, "confidence": "none", "basis": "No problem-solving questions answered yet"}

    # IC — latest attempt of each of the last 5 interview questions
    turns = db.execute(select(InterviewTurn.id, InterviewTurn.parent_turn_id, InterviewTurn.overall_score)
                       .where(InterviewTurn.user_id == user.id, InterviewTurn.evaluation_status == "scored")
                       .order_by(InterviewTurn.answered_at.desc()).limit(60)).all()
    latest_per_q: dict[str, int] = {}
    for tid_, parent, overall in turns:
        root = str(parent or tid_)
        if root not in latest_per_q:
            latest_per_q[root] = overall
        if len(latest_per_q) >= 5:
            break
    if latest_per_q:
        k = len(latest_per_q)
        dims["IC"] = {"score": round(sum(latest_per_q.values()) / k), "confidence": "high" if k >= 4 else "medium"
                      if k >= 2 else "low", "basis": f"Mean of your latest answer to {k} interview question(s)"}
    else:
        dims["IC"] = {"score": None, "confidence": "none", "basis": "No mock interview answers yet"}

    for key in dims:
        dims[key]["name"] = sc.DIMENSION_NAMES[key]
        dims[key]["weight"] = weights.get(key)

    available = {k: v for k, v in dims.items() if v["score"] is not None and k in weights
                 and v["confidence"] in ("medium", "high")}
    index = None
    if len(available) >= 3 and "TK" in available:
        wsum = sum(weights[k] for k in available)
        score = round(sum(weights[k] * available[k]["score"] for k in available) / wsum)
        index = {"score": score, "band": _band(score), "dims_used": sorted(available), "dims_total": len(weights),
                 "note": f"Heuristic summary based on {len(available)} of {len(weights)} dimensions. "
                         "Not a prediction of interview or hiring outcomes."}
    return dims, index


def unassessable_skills(db: Session, states: list[SkillState]) -> list[str]:
    from app.modules.catalog.cache import catalog
    pool = catalog(db).assessment_pool
    return [s.slug for s in states if pool.get(uuid.UUID(s.skill_id), 0) < 2]


def recompute(db: Session, user: User, target: TargetRole, trigger: str) -> GapReport:
    from app.modules.catalog.cache import catalog
    role = catalog(db).roles_by_id[target.role_id]
    reqs = load_requirements(db, target, scored_only=True)
    analysis = latest_analysis(db, user.id, target.id)
    states = compute_states(db, user, target, reqs, analysis=analysis)
    has_resume = analysis is not None
    dims_means = interview_dimension_means(db, user.id)
    gaps = build_gaps(states, has_resume, role.name, prerequisites(db), dims_means)
    dims, index = readiness(db, user, target, states, analysis=analysis)

    prev = db.scalar(select(GapReport).where(GapReport.target_id == target.id)
                     .order_by(GapReport.created_at.desc()).limit(1))
    resolved = []
    if prev is not None:
        prev_gaps = db.scalars(select(SkillGap).where(SkillGap.gap_report_id == prev.id)).all()
        now_keys = {(g["skill_id"] or g["interview_dimension"]): g["type"] for g in gaps}
        names = {s.skill_id: s.name for s in states}
        for pg in prev_gaps:
            key = str(pg.skill_id) if pg.skill_id else pg.interview_dimension
            if key not in now_keys:
                label = names.get(key, key)
                resolved.append({"key": key, "name": label, "previous_type": pg.gap_type,
                                 "text": f"{label} moved from “{sc.GAP_LABELS[pg.gap_type]}” to no open gap."})

    report = GapReport(user_id=user.id, target_id=target.id, trigger=trigger,
                       skill_states=[asdict(s) for s in states], dimension_scores=dims,
                       readiness_index=index["score"] if index else None, resolved=resolved,
                       unassessable=unassessable_skills(db, states), requirements_hash=requirements_hash(reqs),
                       scoring_version=sc.SCORING_VERSION)
    db.add(report)
    db.flush()
    from app.core.db import bulk_insert
    bulk_insert(db, SkillGap, [
        {"id": uuid.uuid4(), "gap_report_id": report.id, "user_id": user.id, "target_id": target.id,
         "skill_id": uuid.UUID(g["skill_id"]) if g["skill_id"] else None,
         "interview_dimension": g["interview_dimension"], "gap_type": g["type"], "importance": g["inputs"]["I"],
         "severity": g["inputs"]["S"], "confidence_multiplier": g["inputs"]["C"], "priority_score": g["priority"],
         "rank": g["rank"], "inputs": g["inputs"],
         "explanation": {"text": g["explanation"], "adjustments": g["adjustments"], "label": g["label"]},
         "next_action": g["next_action"]} for g in gaps])
    # keep the last 50 reports per target (one statement)
    keep = select(GapReport.id).where(GapReport.target_id == target.id).order_by(GapReport.created_at.desc()) \
        .limit(50).scalar_subquery()
    db.execute(delete(GapReport).where(GapReport.target_id == target.id, GapReport.id.not_in(keep)))
    db.commit()
    return report


def report_payload(db: Session, report: GapReport) -> dict:
    gaps = db.scalars(select(SkillGap).where(SkillGap.gap_report_id == report.id).order_by(SkillGap.rank)).all()
    states = {s["skill_id"]: s for s in report.skill_states}
    out = []
    for g in gaps:
        st = states.get(str(g.skill_id)) if g.skill_id else None
        out.append({"id": str(g.id), "type": g.gap_type, "label": g.explanation.get("label"),
                    "skill": {"slug": st["slug"], "name": st["name"]} if st else None,
                    "interview_dimension": g.interview_dimension, "importance": st["importance"] if st else "interview",
                    "priority": g.priority_score, "rank": g.rank, "inputs": g.inputs,
                    "explanation": g.explanation.get("text"), "adjustments": g.explanation.get("adjustments", []),
                    "next_action": g.next_action,
                    "resume_state": st["resume_state"] if st else None,
                    "demonstrated_state": st["demonstrated_state"] if st else None})
    gap_skill_ids = {str(g.skill_id) for g in gaps if g.skill_id}
    strengths = [s for s in report.skill_states if s["demonstrated_state"] == "demonstrated"]
    not_assessed = [s for s in report.skill_states if s["n"] == 0]
    return {"report_id": str(report.id), "created_at": report.created_at.isoformat(), "trigger": report.trigger,
            "gaps": out, "resolved": report.resolved, "skill_states": report.skill_states,
            "strengths": strengths, "not_assessed": not_assessed,
            "no_gap_skills": [s for s in report.skill_states if s["skill_id"] not in gap_skill_ids],
            "unassessable_skills": report.unassessable, "dimension_scores": report.dimension_scores,
            "readiness_index": report.readiness_index, "scoring_version": report.scoring_version,
            "formula": "P = min(100, round(100 × I × S × C) + B)",
            "disclaimer": "Scores are estimates from the evidence you've given so far — not a prediction of "
                          "interviews or offers."}


def latest_report(db: Session, user: User, target: TargetRole) -> GapReport:
    rep = db.scalar(select(GapReport).where(GapReport.target_id == target.id, GapReport.user_id == user.id)
                    .order_by(GapReport.created_at.desc()).limit(1))
    if rep is None or rep.stale:
        rep = recompute(db, user, target, trigger="on_read")
    return rep


def last_activity_marker(db: Session, user: User) -> datetime | None:
    return db.scalar(select(func.max(SkillEvidence.created_at)).where(SkillEvidence.user_id == user.id))
