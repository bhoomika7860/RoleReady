from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import current_user, owned
from app.models import TargetRole, User
from app.modules import hooks
from app.modules.evidence import engine

router = APIRouter(tags=["gaps"])


@router.get("/targets/{target_id}/gap-reports/latest")
def latest(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    return engine.report_payload(db, engine.latest_report(db, user, t))


@router.post("/targets/{target_id}/gap-reports", status_code=201)
def recompute(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    report = hooks.evidence_changed(db, user, t, trigger="manual")
    return engine.report_payload(db, report)


@router.get("/targets/{target_id}/readiness")
def readiness(target_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, TargetRole, target_id, user.id)
    rep = engine.latest_report(db, user, t)
    index = None
    if rep.readiness_index is not None:
        used = [k for k, v in rep.dimension_scores.items() if v.get("score") is not None
                and v.get("confidence") in ("medium", "high")]
        index = {"score": rep.readiness_index, "band": engine._band(rep.readiness_index), "dims_used": used,
                 "note": f"Heuristic summary based on {len(used)} of {len(rep.dimension_scores)} dimensions. "
                         "Not a prediction of interview or hiring outcomes."}
    return {"dimensions": rep.dimension_scores, "index": index, "scoring_version": rep.scoring_version,
            "computed_at": rep.created_at.isoformat()}
