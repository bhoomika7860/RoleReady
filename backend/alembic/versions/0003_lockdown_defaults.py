"""Extend the Data API lockdown to alembic_version and to tables created by future migrations.

Supabase grants anon/authenticated access to new public tables through default privileges; revoking
those defaults (for the migrating role) means later migrations can't accidentally expose tables.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE public."alembic_version" ENABLE ROW LEVEL SECURITY')
    op.execute("""
    DO $$
    DECLARE r text;
    BEGIN
      FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
          EXECUTE format('REVOKE ALL ON TABLE public.alembic_version FROM %I', r);
          EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r);
          EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r);
          EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM %I', r);
        END IF;
      END LOOP;
    END $$;
    """)


def downgrade() -> None:
    op.execute('ALTER TABLE public."alembic_version" DISABLE ROW LEVEL SECURITY')
