from sqlalchemy import select

from app import demo
from app.models import Assessment, PreparationPlan, User


def test_demo_builder_creates_flagged_account_and_refuses_real_accounts(db, fake_ai, monkeypatch):
    monkeypatch.setattr("sys.argv", ["app.demo"])
    assert demo.main() == 0
    user = db.scalar(select(User).where(User.identifier == demo.DEMO_ID))
    assert user.is_demo and user.onboarding_completed_at is not None
    assert db.scalar(select(Assessment).where(Assessment.user_id == user.id)).status in ("scored", "scored_partial")
    assert db.scalar(select(PreparationPlan).where(PreparationPlan.user_id == user.id)) is not None
    # existing → needs --reset; a non-demo account with that identifier is never touched
    assert demo.main() == 1
    user.is_demo = False
    db.commit()
    monkeypatch.setattr("sys.argv", ["app.demo", "--reset"])
    assert demo.main() == 2
