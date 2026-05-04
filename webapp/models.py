"""ORM models: User, Job, ValveRow, Feedback."""
from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, Float, ForeignKey, JSON
from webapp.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user")       # "user" | "annotator" | "super_admin"
    is_active = Column(Boolean, default=True)   # super_admin can deactivate/approve users
    created_at = Column(DateTime, default=datetime.utcnow)
    credits_remaining = Column(Integer, default=10)
    tier = Column(String, default="trial")               # 'trial'|'starter'|'pro'|'enterprise'
    organization = Column(String, nullable=True)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    pid_no = Column(String, default="UNKNOWN")
    status = Column(String, default="pending")  # pending/processing/done/failed
    valve_count = Column(Integer, default=0)
    error_msg = Column(Text, nullable=True)
    output_csv_path = Column(String, nullable=True)
    include_control_valves = Column(Boolean, default=True)
    processing_time = Column(Float, nullable=True)   # seconds
    processing_log = Column(Text, nullable=True)     # captured stdout from pipeline
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    ls_project_id = Column(Integer, nullable=True)   # Label Studio project id
    ls_synced = Column(Boolean, default=False)        # True once tiles pushed to LS
    output_inst_index_path = Column(String, nullable=True)   # instrumentation_index.csv
    output_inst_datasheet_path = Column(String, nullable=True)  # instrument_datasheets.zip


class ValveRow(Base):
    __tablename__ = "valve_rows"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    # 14 CSV columns
    pid_no = Column(String, default="")
    dynamic_code = Column(String, default="-")
    category = Column(String, default="")
    size = Column(String, default="NOT DEFINED")
    area_code = Column(String, default="-")
    serial_no = Column(String, default="")
    series_code = Column(String, default="-")
    fluid_code = Column(String, default="")
    piping_class = Column(String, default="")
    qty = Column(Integer, default=1)
    motor_actuator = Column(String, default="-")
    pneumatic_actuator = Column(String, default="-")
    solenoid = Column(String, default="-")
    line = Column(String, default="")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)            # user-defined label e.g. "production"
    key_prefix = Column(String(8), nullable=False)   # first 8 chars for display
    key_hash = Column(String, nullable=False)         # pbkdf2_sha256 hash of full key
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    delta = Column(Integer, nullable=False)              # signed: positive=grant, negative=consume
    balance_after = Column(Integer, nullable=False)      # snapshot for audit
    reason = Column(String, nullable=False)              # 'signup_grant'|'admin_grant'|'job_consumed'|'purchase'|'refund'
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    meta = Column(Text, nullable=True)                   # JSON string for extra context
    created_at = Column(DateTime, default=datetime.utcnow)


class BillingPlan(Base):
    __tablename__ = "billing_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)                # "Trial" | "Starter" | "Pro" | "Enterprise"
    credits = Column(Integer, nullable=False)
    price_usd_cents = Column(Integer, nullable=False)    # 0 for Trial
    is_active = Column(Boolean, default=True)
    stripe_price_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserFeedback(Base):
    __tablename__ = "user_feedback"                      # distinct from "feedback" (job-level engineer notes)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)   # nullable = anon submissions ok
    category = Column(String, nullable=False)            # 'bug'|'feature'|'pricing'|'other'
    subject = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    page_url = Column(String, nullable=True)
    status = Column(String, default="new")               # 'new'|'in_progress'|'resolved'|'wontfix'
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
