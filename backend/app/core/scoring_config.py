"""Every scoring constant in one place (SRS NFR-029). Changing a value here must bump SCORING_VERSION."""
from __future__ import annotations

SCORING_VERSION = "s1"
RUBRIC_VERSION_INTERVIEW = "ivr-1"
RUBRIC_VERSION_SHORT = "sar-1"

# --- resume coverage (SRS 5.3.2)
REQUIREMENT_WEIGHT = {"core": 3, "required": 2, "preferred": 1}
EVIDENCE_LEVEL_CREDIT = {0: 0.0, 1: 0.4, 2: 0.8, 3: 1.0}
EVIDENCE_LEVEL_LABEL = {0: "Not shown in resume", 1: "Weak evidence", 2: "Evidenced in resume",
                        3: "Evidenced in resume"}
EVIDENCE_LEVEL_STATE = {0: "not_shown", 1: "weak", 2: "evidenced", 3: "evidenced"}
QUANTIFIED_UNITS = ("%", "x", "ms", "s", "sec", "seconds", "users", "requests", "records", "k", "lakh", "rows",
                    "students", "customers", "hours", "minutes", "days", "mb", "gb", "tb", "qps", "rps")

# --- question scoring (SRS 5.4)
DIFFICULTY_WEIGHT = {"easy": 1.0, "medium": 1.5, "hard": 2.0}
INTERVIEW_DIFFICULTY_WEIGHT = 1.5
SHORT_ANSWER_MIN_WORDS = 10
INTERVIEW_MIN_WORDS = 20
KEY_POINT_CREDIT = {"covered": 1.0, "partial": 0.5, "missing": 0.0}

# --- skill state and gaps (SRS FR-050, 5.5)
EVIDENCE_WINDOW = 12
IMPORTANCE_WEIGHT = {"core": 1.0, "required": 0.75, "preferred": 0.40}
INTERVIEW_GAP_IMPORTANCE = 0.80


def confidence_multiplier(n: int) -> float:
    if n == 0:
        return 0.70
    if n <= 2:
        return 0.80
    if n <= 5:
        return 0.90
    return 1.00


PREREQ_BONUS = 10
PREREQ_PENALTY = 0.6
NO_GAP_D = 0.70
NO_GAP_R = 2

GAP_LABELS = {
    "G1": "Not yet evidenced",
    "G2": "Weak demonstrated skill",
    "G3": "Resume claim at risk",
    "G4": "Demonstrated but not on resume",
    "G5": "Not yet assessed",
    "G6": "Interview weakness",
}

# --- planner (SRS 5.6)
PLAN_HORIZON_MIN, PLAN_HORIZON_MAX = 3, 42
PLAN_SLACK = 0.85
PLAN_MAX_SKILLS_PER_DAY = 2
TASK_MINUTES = {"learn_cap": 40, "practice": 25, "reassess": 15, "resume": 15, "interview": 20, "assess": 25}
REPLAN_PRIORITY_DELTA = 10

# --- readiness (SRS 9)
DIMENSIONS = ("RA", "TK", "PS", "PE", "IC")
DIMENSION_NAMES = {"RA": "Resume alignment", "TK": "Technical knowledge", "PS": "Problem solving",
                   "PE": "Project & experience evidence", "IC": "Interview communication"}
READINESS_BANDS = ((75, "Strong"), (60, "Approaching"), (40, "Developing"), (0, "Early"))

# --- comparability (SRS 9.6)
NO_CLEAR_CHANGE_DELTA = 17
MIN_COMPARABLE_ITEMS = 4

# --- assessments
DIAGNOSTIC_ITEMS = 15
CHECKPOINT_ITEMS = 6
ASSESSMENT_TTL_HOURS = 48
INTERVIEW_MAX_QUESTIONS = 5
INTERVIEW_MAX_ATTEMPTS = 3
INTERVIEW_INACTIVITY_HOURS = 2
PRACTICE_SET_SIZE = 5
READY_TO_REASSESS_PRACTICE = 5
