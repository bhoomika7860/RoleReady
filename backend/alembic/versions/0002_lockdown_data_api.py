"""Lock application tables away from Supabase's public Data API.

Access strategy: the browser never talks to the database. Only the FastAPI backend connects (as the
table owner via DATABASE_URL) and enforces per-user ownership in every query. To make sure the
Supabase REST/GraphQL Data API (anon / authenticated roles) cannot read or write these tables even if
someone uses the project's anon key, we enable Row Level Security on every table with NO policies
(deny-all for non-owner roles) and revoke table privileges from those roles. RLS is not disabled
anywhere; the owner role bypasses it by design, so the backend keeps working.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = [
    "users", "user_sessions", "roles", "skills", "skill_prerequisites", "role_skills", "target_roles",
    "job_descriptions", "job_requirements", "resumes", "resume_versions", "resume_analyses", "rewrite_suggestions",
    "questions", "assessments", "assessment_items", "practice_attempts", "interview_sessions", "interview_turns",
    "skill_evidence", "gap_reports", "skill_gaps", "learning_resources", "resource_skills", "preparation_plans",
    "preparation_tasks", "ai_requests",
]


def upgrade() -> None:
    for t in TABLES:
        op.execute(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY')
    op.execute("""
    DO $$
    DECLARE r text;
    BEGIN
      FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
          EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
          EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
        END IF;
      END LOOP;
    END $$;
    """)


def downgrade() -> None:
    for t in TABLES:
        op.execute(f'ALTER TABLE public."{t}" DISABLE ROW LEVEL SECURITY')
