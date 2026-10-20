"""Diagnostic and checkpoint assessments (SRS 5.4)."""
from __future__ import annotations

import random
import secrets
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai.gateway import AIFailed, AIGateway
from app.core import scoring_config as sc
from app.core.db import bulk_insert
from app.core.errors import AIQuotaExceeded, AIUnavailableError, AppError, Conflict, NotFound, ValidationFailed
from app.core.security import utcnow
from app.models import (OBJECTIVE_TYPES, Assessment, AssessmentItem, PracticeAttempt, Question, Role, Skill,
                        SkillEvidence, TargetRole, User)
from app.modules.assessments.scoring import evaluate_short, is_answered, score_objective
from app.modules.targets.requirements import load_requirements

SHORT_TYPES = ("short_answer", "approach")
DIFFS = ("easy", "medium", "hard")
_eval_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="eval")


class InsufficientQuestions(AppError):
    status_code, code = 422, "INSUFFICIENT_QUESTIONS"
    message = "There aren't enough questions in the bank for this yet."


def _pool(db: Session, skill_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Question]]:
    rows = db.scalars(select(Question).where(Question.skill_id.in_(skill_ids), Question.status == "active",
                                             Question.owner_user_id.is_(None),
                                             Question.purpose.in_(("assessment", "any")))
                      .order_by(Question.slug)).all()
    pool: dict[uuid.UUID, list[Question]] = {sid: [] for sid in skill_ids}
    for q in rows:
        pool[q.skill_id].append(q)
    return pool


def _recently_seen(db: Session, user_id: uuid.UUID, days: int = 30) -> dict[uuid.UUID, object]:
    since = utcnow() - timedelta(days=days)
    seen: dict[uuid.UUID, object] = {}
    for qid, ts in db.execute(select(AssessmentItem.question_id, func.max(AssessmentItem.created_at))
                              .where(AssessmentItem.user_id == user_id).group_by(AssessmentItem.question_id)).all():
        seen[qid] = ts
    for qid, ts in db.execute(select(PracticeAttempt.question_id, func.max(PracticeAttempt.created_at))
                              .where(PracticeAttempt.user_id == user_id)
                              .group_by(PracticeAttempt.question_id)).all():
        seen[qid] = max(ts, seen.get(qid, ts))
    return {k: v for k, v in seen.items() if v >= since}


def _pick(cands: list[Question], used: set, seen: dict, rng: random.Random, prefer) -> Question | None:
    avail = [q for q in cands if q.id not in used]
    if not avail:
        return None
    rng.shuffle(avail)
    avail.sort(key=lambda q: (0 if prefer(q) else 1, 0 if q.id not in seen else 1))
    return avail[0]


def _near(d: str) -> list[str]:
    return {"easy": ["easy", "medium", "hard"], "medium": ["medium", "easy", "hard"],
            "hard": ["hard", "medium", "easy"]}[d]


def build_diagnostic(db: Session, user: User, target: TargetRole, seed: int) -> tuple[list[Question], dict]:
    reqs = [r for r in load_requirements(db, target, scored_only=True) if r.skill_id]
    pool = _pool(db, [r.skill_id for r in reqs])
    eligible = [r for r in reqs if len(pool[r.skill_id]) >= 2]
    unassessable = [r.skill_slug for r in reqs if len(pool[r.skill_id]) < 2]
    if sum(len(pool[r.skill_id]) for r in eligible) < 8:
        raise InsufficientQuestions("The question bank doesn't have enough items for this role yet "
                                    "(needs at least 8). Run the seed command.")
    rng = random.Random(seed)
    seen = _recently_seen(db, user.id)

    slots: list[tuple] = []  # (req, difficulty, want_short)
    for i, r in enumerate(eligible[:3]):
        slots += [(r, "easy", False), (r, "medium", True), (r, "hard", False)]
    for r in eligible[3:6]:
        slots += [(r, "easy", False), (r, "medium", False)]
    for r in eligible[6:]:
        if len(slots) >= sc.DIAGNOSTIC_ITEMS:
            break
        slots += [(r, "easy", False), (r, "medium", False)]
    extra_round = 0
    while len(slots) < sc.DIAGNOSTIC_ITEMS and extra_round < 4:  # small requirement sets: add depth to top skills
        for r in eligible[:3]:
            slots.append((r, rng.choice(DIFFS), False))
        extra_round += 1
    slots = slots[:sc.DIAGNOSTIC_ITEMS]

    chosen: list[Question] = []
    used: set = set()
    alloc: Counter = Counter()
    for r, diff, want_short in slots:
        q = None
        for d in _near(diff):
            cands = [x for x in pool[r.skill_id] if x.difficulty == d]
            q = _pick(cands, used, seen, rng, (lambda x: x.type in SHORT_TYPES) if want_short
                      else (lambda x: x.type in OBJECTIVE_TYPES))
            if q:
                break
        if q is None:  # skill exhausted → give the slot to the next skill with spare items
            for r2 in eligible:
                q = _pick(pool[r2.skill_id], used, seen, rng, lambda x: x.type in OBJECTIVE_TYPES)
                if q:
                    break
        if q is not None:
            chosen.append(q)
            used.add(q.id)
            alloc[q.skill_id] += 1

    # exactly 3 short answers when available; at least 3 problem-solving items
    def swap(pred_out, pred_in, needed: int) -> None:
        for i, q in enumerate(list(chosen)):
            if needed <= 0:
                return
            if not pred_out(q):
                continue
            repl = _pick([x for x in pool[q.skill_id] if x.difficulty == q.difficulty and pred_in(x)], used, seen,
                         rng, lambda x: True)
            if repl:
                used.add(repl.id)
                chosen[i] = repl
                needed -= 1

    n_short = sum(1 for q in chosen if q.type in SHORT_TYPES)
    if n_short > 3:
        swap(lambda q: q.type in SHORT_TYPES, lambda x: x.type in OBJECTIVE_TYPES, n_short - 3)
    elif n_short < 3:
        swap(lambda q: q.type in OBJECTIVE_TYPES and q.difficulty == "medium", lambda x: x.type in SHORT_TYPES,
             3 - n_short)
    n_ps = sum(1 for q in chosen if q.type in ("code_output", "approach"))
    if n_ps < 3:
        swap(lambda q: q.type in ("mcq_single", "mcq_multi"), lambda x: x.type == "code_output", 3 - n_ps)

    blueprint = {
        "kind": "diagnostic", "seed": seed,
        "allocation": {str(sid): n for sid, n in alloc.items()},
        "skills": [{"slug": r.skill_slug, "importance": r.importance, "items": sum(1 for q in chosen
                                                                                     if q.skill_id == r.skill_id)}
                   for r in eligible if any(q.skill_id == r.skill_id for q in chosen)],
        "difficulty_mix": dict(Counter(q.difficulty for q in chosen)),
        "type_mix": dict(Counter(q.type for q in chosen)),
        "unassessable": unassessable, "includes_repeats": any(q.id in seen for q in chosen),
    }
    return chosen, blueprint


def build_checkpoint(db: Session, user: User, target: TargetRole, skill: Skill, seed: int) -> tuple[list[Question],
                                                                                                    dict]:
    pool = _pool(db, [skill.id])[skill.id]
    if len(pool) < sc.CHECKPOINT_ITEMS:
        raise InsufficientQuestions(f"There aren't enough {skill.name} questions for a checkpoint yet "
                                    f"(needs {sc.CHECKPOINT_ITEMS}).")
    prev = db.scalar(select(Assessment).where(Assessment.user_id == user.id, Assessment.kind == "checkpoint",
                                              Assessment.skill_id == skill.id,
                                              Assessment.status.in_(("scored", "scored_partial")))
                     .order_by(Assessment.created_at.desc()).limit(1))
    if prev is not None and prev.blueprint.get("slots"):
        slots = [tuple(s) for s in prev.blueprint["slots"]]
    else:
        slots = [("easy", "objective"), ("easy", "objective"), ("medium", "short"), ("medium", "objective"),
                 ("hard", "objective"), ("hard", "objective")]
        if not any(q.type in SHORT_TYPES and q.difficulty == "medium" for q in pool):
            slots[2] = ("medium", "objective")
    used_before = set(db.scalars(select(AssessmentItem.question_id).where(AssessmentItem.user_id == user.id,
                                                                          AssessmentItem.skill_id == skill.id)).all())
    rng = random.Random(seed)
    chosen: list[Question] = []
    used: set = set()
    repeats = False
    for diff, kind in slots:
        want = (lambda x: x.type in SHORT_TYPES) if kind == "short" else (lambda x: x.type in OBJECTIVE_TYPES)
        q = None
        for strict in (True, False):  # first: matching type & unused before; then relax
            for d in ([diff] if strict else _near(diff)):
                cands = [x for x in pool if x.difficulty == d and (want(x) or not strict)]
                fresh = [x for x in cands if x.id not in used_before]
                q = _pick(fresh, used, {}, rng, want) or (None if strict else _pick(cands, used, {}, rng, want))
                if q:
                    break
            if q:
                break
        if q is None:
            q = _pick(pool, used, {}, rng, want)
        if q is not None:
            repeats = repeats or q.id in used_before
            chosen.append(q)
            used.add(q.id)
    blueprint = {"kind": "checkpoint", "seed": seed, "skill": skill.slug,
                 "slots": [[q.difficulty, "short" if q.type in SHORT_TYPES else "objective"] for q in chosen],
                 "difficulty_mix": dict(Counter(q.difficulty for q in chosen)),
                 "type_mix": dict(Counter(q.type for q in chosen)), "includes_repeats": repeats,
                 "copied_from": str(prev.id) if prev is not None else None}
    return chosen, blueprint


def start(db: Session, user: User, target: TargetRole, kind: str, skill_slug: str | None) -> Assessment:
    if target.status != "active":
        raise Conflict("Archived targets are read-only.", code="TARGET_ARCHIVED")
    expire_stale(db, user)
    if kind == "diagnostic":
        existing = db.scalar(select(Assessment).where(Assessment.target_id == target.id,
                                                      Assessment.kind == "diagnostic",
                                                      Assessment.status == "in_progress"))
        if existing is not None:
            return existing
        seed = secrets.randbits(48)
        questions, blueprint = build_diagnostic(db, user, target, seed)
        skill_id = None
    else:
        if not skill_slug:
            raise ValidationFailed(details={"fields": {"skill_slug": "Choose a skill for the checkpoint."}})
        skill = db.scalar(select(Skill).where(Skill.slug == skill_slug))
        reqs = load_requirements(db, target, scored_only=True)
        if skill is None or skill.id not in {r.skill_id for r in reqs}:
            raise ValidationFailed(details={"fields": {"skill_slug": "That skill isn't one of this target's "
                                                                    "requirements."}})
        existing = db.scalar(select(Assessment).where(Assessment.target_id == target.id,
                                                      Assessment.kind == "checkpoint", Assessment.skill_id == skill.id,
                                                      Assessment.status == "in_progress"))
        if existing is not None:
            return existing
        seed = secrets.randbits(48)
        questions, blueprint = build_checkpoint(db, user, target, skill, seed)
        skill_id = skill.id
    a = Assessment(user_id=user.id, target_id=target.id, kind=kind, skill_id=skill_id, status="in_progress",
                   blueprint=blueprint, seed=seed, scoring_version=sc.SCORING_VERSION,
                   expires_at=utcnow() + timedelta(hours=sc.ASSESSMENT_TTL_HOURS), items_total=len(questions))
    db.add(a)
    db.flush()
    bulk_insert(db, AssessmentItem, [
        {"id": uuid.uuid4(), "assessment_id": a.id, "user_id": user.id, "position": pos, "question_id": q.id,
         "skill_id": q.skill_id, "difficulty": q.difficulty, "type": q.type, "unanswered": False,
         "evaluation_status": "not_required" if q.type in OBJECTIVE_TYPES else "pending"}
        for pos, q in enumerate(questions, 1)])
    db.commit()
    return a


def items_with_questions(db: Session, a: Assessment) -> list[tuple[AssessmentItem, Question, Skill]]:
    return db.execute(select(AssessmentItem, Question, Skill)
                      .join(Question, Question.id == AssessmentItem.question_id)
                      .join(Skill, Skill.id == AssessmentItem.skill_id)
                      .where(AssessmentItem.assessment_id == a.id).order_by(AssessmentItem.position)).all()


def _evidence_row(a: Assessment, item: AssessmentItem, score, incomplete: bool) -> dict:
    return {"id": uuid.uuid4(), "user_id": a.user_id, "target_id": a.target_id, "skill_id": item.skill_id,
            "source_type": "assessment", "score": score,
            "difficulty_weight": Decimal(str(sc.DIFFICULTY_WEIGHT[item.difficulty])), "item_type": item.type,
            "incomplete_attempt": incomplete, "assessment_item_id": item.id, "observed_at": a.submitted_at or utcnow()}


def _write_item_evidence(db: Session, a: Assessment, item: AssessmentItem, incomplete: bool) -> None:
    if item.score is None or item.unanswered:
        return
    bulk_insert(db, SkillEvidence, [_evidence_row(a, item, item.score, incomplete)])


def _bulk_update_items(db: Session, values: dict[uuid.UUID, dict]) -> None:
    """One batched UPDATE-by-primary-key round trip instead of one UPDATE per item."""
    if not values:
        return
    groups: dict[tuple, list[dict]] = {}
    for item_id, cols in values.items():
        groups.setdefault(tuple(sorted(cols)), []).append({"id": item_id, **cols})
    for rows in groups.values():
        db.execute(update(AssessmentItem), rows)
    db.expire_all()


def _finalise_score(db: Session, a: Assessment) -> None:
    items = db.scalars(select(AssessmentItem).where(AssessmentItem.assessment_id == a.id)).all()
    scored = [i for i in items if i.score is not None]
    w = sum(sc.DIFFICULTY_WEIGHT[i.difficulty] for i in scored)
    a.items_scored = len(scored)
    a.score = Decimal(str(round(sum(sc.DIFFICULTY_WEIGHT[i.difficulty] * float(i.score) for i in scored) / w, 3))) \
        if w else None
    if a.status != "abandoned":
        a.status = "scored_partial" if any(i.evaluation_status in ("failed", "pending") for i in items) else "scored"
    a.scored_at = a.scored_at or utcnow()


def submit(db: Session, user: User, a: Assessment, gateway: AIGateway) -> Assessment:
    res = db.execute(update(Assessment).where(Assessment.id == a.id, Assessment.user_id == user.id,
                                              Assessment.status == "in_progress", Assessment.expires_at > utcnow())
                     .values(status="scoring", submitted_at=utcnow()))
    db.commit()
    if res.rowcount != 1:
        db.refresh(a)
        raise Conflict("This assessment has already been submitted or has expired.", code="ASSESSMENT_CLOSED",
                       details={"status": a.status})
    db.refresh(a)
    rows = items_with_questions(db, a)
    # plain copies so later bulk updates (which expire ORM state) don't trigger per-item reloads
    snapshot = [(SimpleNamespace(id=item.id, skill_id=item.skill_id, difficulty=item.difficulty, type=item.type,
                                 response=item.response), q) for item, q, _ in rows]
    to_eval = []
    first: dict[uuid.UUID, dict] = {}
    final_scores: dict[uuid.UUID, Decimal | None] = {}
    for item, q in snapshot:
        if not is_answered(item.type, item.response):
            first[item.id] = {"unanswered": True, "score": Decimal("0"),
                              "evaluation_status": "not_required" if item.type in OBJECTIVE_TYPES else "scored"}
            continue
        if item.type in OBJECTIVE_TYPES:
            score = Decimal(str(round(score_objective(item.type, q.correct_answer, item.response), 3)))
            first[item.id] = {"score": score}
            final_scores[item.id] = score
        else:
            # plain snapshot: evaluation runs in worker threads and must not touch the ORM session
            q_snap = SimpleNamespace(id=q.id, prompt=q.prompt, rubric=q.rubric, reference_answer=q.reference_answer,
                                     type=q.type)
            to_eval.append((item, q_snap, item.response.get("text", "")))
    _bulk_update_items(db, first)
    db.commit()  # objective scores are durable before any AI call

    from app.modules.catalog.cache import catalog
    target = db.get(TargetRole, a.target_id)
    role_name = catalog(db).roles_by_id[target.role_id].name
    results = _evaluate_many(gateway, [(item.id, q, text) for item, q, text in to_eval], user.id, role_name)
    second: dict[uuid.UUID, dict] = {}
    for item, q, _ in to_eval:
        r = results[item.id]
        if r.get("error"):
            # excluded from scoring — never counted as zero
            second[item.id] = {"evaluation_status": "failed", "evaluation": {"error": r["error"]}}
        else:
            score = Decimal(str(r["score"]))
            second[item.id] = {"score": score, "evaluation": r["evaluation"], "evaluation_status": "scored",
                               "rubric_version": (q.rubric or {}).get("version"), "prompt_version": "w7s.v1"}
            final_scores[item.id] = score
    _bulk_update_items(db, second)
    bulk_insert(db, SkillEvidence, [_evidence_row(a, item, final_scores[item.id], False)
                                    for item, _q in snapshot if final_scores.get(item.id) is not None])
    a = db.get(Assessment, a.id)
    _finalise_score(db, a)
    db.commit()
    return a


def _evaluate_many(gateway: AIGateway, jobs: list[tuple], user_id, role_name: str) -> dict:
    def one(job):
        item_id, q, text = job
        try:
            return item_id, evaluate_short(gateway, q, text, user_id, role_name)
        except (AIFailed, AIUnavailableError, AIQuotaExceeded) as exc:
            return item_id, {"error": exc.code}
    return dict(_eval_pool.map(one, jobs)) if jobs else {}


def retry_evaluation(db: Session, user: User, a: Assessment, position: int, gateway: AIGateway) -> AssessmentItem:
    item = db.scalar(select(AssessmentItem).where(AssessmentItem.assessment_id == a.id,
                                                  AssessmentItem.position == position))
    if item is None:
        raise NotFound()
    if a.status in ("in_progress", "scoring") or item.evaluation_status not in ("failed", "pending") \
            or item.type in OBJECTIVE_TYPES:
        raise Conflict("This answer doesn't need re-evaluation.", code="NOT_RETRYABLE")
    q = db.get(Question, item.question_id)
    role = db.get(Role, db.get(TargetRole, a.target_id).role_id)
    r = evaluate_short(gateway, q, (item.response or {}).get("text", ""), user.id, role.name)  # errors propagate
    item.score, item.evaluation, item.evaluation_status = Decimal(str(r["score"])), r["evaluation"], "scored"
    item.rubric_version, item.prompt_version = (q.rubric or {}).get("version"), "w7s.v1"
    db.flush()
    _write_item_evidence(db, a, item, incomplete=a.status == "abandoned")
    _finalise_score(db, a)
    db.commit()
    return item


def expire_stale(db: Session, user: User) -> list[Assessment]:
    """Lazy maintenance: expired in-progress attempts become abandoned; answered objective items still count."""
    stale = db.scalars(select(Assessment).where(Assessment.user_id == user.id, Assessment.status == "in_progress",
                                                Assessment.expires_at <= utcnow())).all()
    for a in stale:
        a.status = "abandoned"
        for item, q, _ in items_with_questions(db, a):
            if item.type in OBJECTIVE_TYPES and is_answered(item.type, item.response):
                item.score = Decimal(str(score_objective(item.type, q.correct_answer, item.response)))
                db.flush()
                _write_item_evidence(db, a, item, incomplete=True)
            elif item.type not in OBJECTIVE_TYPES and is_answered(item.type, item.response):
                item.evaluation_status = "pending"
            else:
                item.unanswered = True
        _finalise_score(db, a)
    if stale:
        db.commit()
    return list(stale)
