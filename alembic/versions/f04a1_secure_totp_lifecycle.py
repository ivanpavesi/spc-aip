"""F04: contatori TOTP, versione sessioni ed enrollment con scadenza.

Revision ID: f04a1
Revises: 84d60c0c67b2
"""
from alembic import op
import sqlalchemy as sa

revision = "f04a1"
down_revision = "84d60c0c67b2"
branch_labels = None
depends_on = None


def upgrade():
    # Additiva: non modifica credenziali, fattori, ruoli o sessioni esistenti.
    op.add_column("users", sa.Column("mfa_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("totp_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("totp_last_counter", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("mfa_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("mfa_locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("auth_sessions", sa.Column("mfa_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("auth_sessions", sa.Column("totp_pending_secret", sa.Text(), nullable=True))
    op.add_column("auth_sessions", sa.Column("totp_pending_at", sa.DateTime(timezone=True), nullable=True))
    # SQLite non applica il limite VARCHAR; evita una ricostruzione con FK attive.
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("users", "totp_secret", existing_type=sa.String(64), type_=sa.Text())


def downgrade():
    # Rifiuta perdita di dati: il codice precedente non legge i nuovi segreti cifrati.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM users WHERE totp_secret LIKE 'enc:%'")).scalar():
        raise RuntimeError("Downgrade non sicuro: presenti fattori F04 cifrati; mantenere schema e codice F04.")
    if bind.dialect.name == "postgresql":
        op.alter_column("users", "totp_secret", existing_type=sa.Text(), type_=sa.String(64))
    for name in ("totp_pending_at", "totp_pending_secret", "mfa_version"):
        op.drop_column("auth_sessions", name)
    for name in ("mfa_locked_until", "mfa_failures", "totp_last_counter", "totp_required", "mfa_version"):
        op.drop_column("users", name)
