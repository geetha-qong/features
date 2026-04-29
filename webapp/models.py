"""ORM models: User, Job, ValveRow, Feedback."""
from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, Float, ForeignKey
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
    output_inst_index_path = Column(String, nullable=True)  # instrumentation_index.csv


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
