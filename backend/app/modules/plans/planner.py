"""Deterministic study planner (SRS 5.6). Pure function: same inputs → same plan; no LLM.

Gaps are turned into short task sequences by type, then packed into days in priority order without
exceeding the daily time budget, at most two distinct skills per day, with re-checks scheduled at
least a day after practice. Work that cannot fit before the deadline is listed as unscheduled —
never silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core import scoring_config as sc


@dataclass
class TaskSpec:
    task_type: str
    minutes: int
    title: str
    description: str
    rationale: str
    seq_key: str
    step_index: int
    skill_id: str | None = None
    skill_slug: str | None = None
    skill_name: str | None = None
    interview_dimension: str | None = None
    gap_type: str | None = None
    priority: int = 0
    resource_id: str | None = None
    min_gap_after_prev_days: int = 0


@dataclass
class PlannedTask(TaskSpec):
    scheduled_date: date | None = None
    position: int = 0


@dataclass
class GapInput:
    gap_type: str
    priority: int
    skill_id: str | None
    skill_slug: str | None
    skill_name: str | None
    importance: str
    D: float | None
    n: int
    interview_dimension: str | None = None
    prerequisite_ids: set[str] = field(default_factory=set)


@dataclass
class Resource:
    id: str
    title: str
    minutes: int


@dataclass
class PlanResult:
    days: list[tuple[date, list[PlannedTask]]]
    unscheduled: list[dict]
    horizon_days: int
    capacity: int


def _why(g: GapInput) -> str:
    if g.gap_type in ("G2", "G3"):
        return (f"Scheduled because {g.skill_name} is a {g.importance} requirement and your recent answers "
                f"averaged {round((g.D or 0) * 100)}% over {g.n} questions.")
    if g.gap_type == "G4":
        return f"You've shown {g.skill_name}, but your resume doesn't show it in use yet."
    if g.gap_type == "G6":
        return f"Your recent interview answers were weakest on {g.interview_dimension}."
    return f"Scheduled because {g.skill_name} is a {g.importance} requirement with no measurement yet."


def template(g: GapInput, resource: Resource | None) -> list[TaskSpec]:
    key = f"{g.skill_slug or g.interview_dimension}:{g.gap_type}"
    base = dict(seq_key=key, skill_id=g.skill_id, skill_slug=g.skill_slug, skill_name=g.skill_name,
                interview_dimension=g.interview_dimension, gap_type=g.gap_type, priority=g.priority,
                rationale=_why(g)[:300])
    m = sc.TASK_MINUTES
    name = g.skill_name or g.interview_dimension or ""
    n_practice = 2 if g.gap_type == "G3" else 1
    practice = lambda i, after=0: TaskSpec(  # noqa: E731
        "practice", m["practice"],
        f"Practise {name} — 5 questions" + (f" (set {i + 1} of {n_practice})" if n_practice > 1 else ""),
                                           f"Answer 5 {name} practice questions and read each explanation.",
                                           step_index=i, min_gap_after_prev_days=after, **base)
    reassess = lambda i: TaskSpec("reassess", m["reassess"], f"{name} checkpoint (6 questions)",  # noqa: E731
                                  f"Re-measure {name} with a 6-question checkpoint comparable to earlier ones.",
                                  step_index=i, min_gap_after_prev_days=1, **base)
    if g.gap_type == "G2":
        seq = []
        if resource is not None:
            seq.append(TaskSpec("learn", min(resource.minutes, m["learn_cap"]), f"Learn {name}: {resource.title}"[:150],
                                f"Work through “{resource.title}”, then mark this task done.",
                                step_index=0, resource_id=resource.id, **base))
        seq += [practice(1), reassess(2)]
        return seq
    if g.gap_type == "G3":
        return [practice(0), practice(1), reassess(2)]
    if g.gap_type in ("G1", "G5"):
        return [reassess(0)]
    if g.gap_type == "G4":
        return [TaskSpec("resume", m["resume"], f"Add {name} evidence to your resume",
                         f"If you've used {name} in a project or internship, describe how in that entry's bullets.",
                         step_index=0, **base)]
    if g.gap_type == "G6":
        title = f"Mock interview — focus on {name}"
        return [TaskSpec("interview", m["interview"], title, f"Answer interview questions; aim to improve {name}.",
                         step_index=0, **base),
                TaskSpec("interview", m["interview"], title, f"Second session on {name}, after reviewing feedback.",
                         step_index=1, min_gap_after_prev_days=2, **base)]
    return []


def diagnostic_sequence() -> list[TaskSpec]:
    return [TaskSpec("assess", sc.TASK_MINUTES["assess"], "Take your diagnostic assessment (15 questions)",
                     "Measures your current level in the role's most important skills.",
                     "Everything else in the plan depends on knowing where you stand.", seq_key="diagnostic",
                     step_index=0, priority=100)]


def build_plan(gaps: list[GapInput], today: date, deadline: date, capacity: int, completed: set[tuple[str, int]],
               resources: dict[str, Resource | None], has_diagnostic: bool,
               maintenance_skill: GapInput | None = None) -> PlanResult:
    horizon = max(sc.PLAN_HORIZON_MIN, min(sc.PLAN_HORIZON_MAX, (deadline - today).days))
    budget = horizon * capacity * sc.PLAN_SLACK
    queue: list[list[TaskSpec]] = []
    unscheduled: list[dict] = []

    if not has_diagnostic:
        queue.append(diagnostic_sequence())
        budget -= sc.TASK_MINUTES["assess"]
    for g in sorted(gaps, key=lambda x: (-x.priority, x.skill_name or x.interview_dimension or "")):
        seq = [t for t in template(g, resources.get(g.skill_id or "")) if (t.seq_key, t.step_index) not in completed]
        for t in seq:
            if t.task_type == "learn":
                t.minutes = min(t.minutes, capacity)
        if not seq:
            continue
        need = sum(t.minutes for t in seq)
        if need > budget or any(t.minutes > capacity for t in seq):
            unscheduled.append({"skill": g.skill_name or g.interview_dimension, "gap_type": g.gap_type,
                                "priority": g.priority, "reason": "Not enough time before your deadline"})
            continue
        budget -= need
        queue.append(seq)
    if not gaps and has_diagnostic and maintenance_skill is not None:
        for k in range(0, horizon, 3):
            queue.append([TaskSpec("reassess", sc.TASK_MINUTES["reassess"],
                                   f"{maintenance_skill.skill_name} checkpoint (maintenance)",
                                   "No open gaps — keep your evidence fresh on a core skill.",
                                   "Scheduled to keep your lowest-confidence core skill measured.",
                                   seq_key=f"maintenance:{maintenance_skill.skill_slug}:{k}", step_index=0,
                                   skill_id=maintenance_skill.skill_id, skill_slug=maintenance_skill.skill_slug,
                                   skill_name=maintenance_skill.skill_name, priority=30)])

    # prerequisite skills' sequences come before their dependants' (stable otherwise)
    def prereq_rank(seq: list[TaskSpec]) -> int:
        sid = seq[0].skill_id
        return 0 if any(sid and sid in g.prerequisite_ids for g in gaps) else 1
    if not has_diagnostic:
        head, rest = queue[:1], queue[1:]
    else:
        head, rest = [], queue
    rest.sort(key=prereq_rank)
    queue = head + rest

    days = [(today + timedelta(days=i)) for i in range(horizon)]
    free = {d: capacity for d in days}
    skills_on: dict[date, set[str]] = {d: set() for d in days}
    placed: dict[date, list[PlannedTask]] = {d: [] for d in days}
    for seq in queue:
        earliest = today
        prev_day: date | None = None
        for i, spec in enumerate(seq):
            min_day = earliest
            if prev_day is not None and spec.min_gap_after_prev_days:
                min_day = max(min_day, prev_day + timedelta(days=spec.min_gap_after_prev_days))
            skill_key = spec.skill_slug or spec.interview_dimension or spec.seq_key
            day = next((d for d in days if d >= min_day and free[d] >= spec.minutes and
                        (skill_key in skills_on[d] or len(skills_on[d]) < sc.PLAN_MAX_SKILLS_PER_DAY)), None)
            if day is None:
                for rest_spec in seq[i:]:
                    unscheduled.append({"skill": rest_spec.skill_name or rest_spec.interview_dimension or "Diagnostic",
                                        "gap_type": rest_spec.gap_type, "priority": rest_spec.priority,
                                        "task": rest_spec.title, "reason": "Didn't fit before your deadline"})
                break
            free[day] -= spec.minutes
            skills_on[day].add(skill_key)
            placed[day].append(PlannedTask(**spec.__dict__, scheduled_date=day))
            earliest, prev_day = day, day
    out_days = []
    for d in days:
        for pos, t in enumerate(placed[d]):
            t.position = pos
        if placed[d]:
            out_days.append((d, placed[d]))
    return PlanResult(out_days, unscheduled, horizon, capacity)
