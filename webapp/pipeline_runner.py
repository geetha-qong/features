"""
Adapter: runs the existing pipeline.run() in a per-job directory,
then stores results in the database.
"""
import csv
import io
import os
import sys
import threading
import time
import traceback
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from webapp import models
from webapp.config import JOB_OUTPUT_DIR

_pipeline_lock = threading.Lock()

# Add project root to sys.path so pipeline imports work
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def run_pipeline_for_job(job_id: int, pdf_path: str, pid_no_override: str, db: Session, include_control_valves: bool = True) -> None:
    """
    Called in a background thread. Runs the pipeline and updates the DB.
    """
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        return

    job.status = "processing"
    db.commit()

    job_dir = JOB_OUTPUT_DIR / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = job_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    output_csv = str(job_dir / "valve_list.csv")

    original_cwd = os.getcwd()
    log_buffer = io.StringIO()
    start_time = time.time()
    try:
        with _pipeline_lock:
            os.chdir(str(job_dir))
            Path("tmp").mkdir(exist_ok=True)

            import importlib
            import pipeline as pl
            importlib.reload(pl)

            with redirect_stdout(log_buffer):
                pl.run(pdf_path=pdf_path, output_path=output_csv)

    except Exception as exc:
        os.chdir(original_cwd)
        job.status = "failed"
        job.error_msg = traceback.format_exc()
        job.processing_time = round(time.time() - start_time, 1)
        job.processing_log = log_buffer.getvalue()
        job.completed_at = datetime.utcnow()
        db.commit()
        return
    finally:
        os.chdir(original_cwd)

    # Read CSV → insert valve rows
    try:
        _ingest_csv(job_id, output_csv, pid_no_override, db, include_control_valves)
    except Exception as exc:
        job.status = "failed"
        job.error_msg = f"CSV ingest error: {traceback.format_exc()}"
        job.completed_at = datetime.utcnow()
        db.commit()
        return

    job.status = "done"
    job.output_csv_path = output_csv
    job.completed_at = datetime.utcnow()
    job.processing_time = round(time.time() - start_time, 1)
    job.processing_log = log_buffer.getvalue()
    job.valve_count = db.query(models.ValveRow).filter(models.ValveRow.job_id == job_id).count()
    db.commit()


def _ingest_csv(job_id: int, csv_path: str, pid_no_override: str, db: Session, include_control_valves: bool = True) -> None:
    """Read the output CSV and insert rows into valve_rows table."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not include_control_valves and row.get("Category", "").strip().upper() == "CV":
                continue
            valve = models.ValveRow(
                job_id=job_id,
                pid_no=pid_no_override or row.get("P&ID No", ""),
                dynamic_code=row.get("Dynamic Code", "-"),
                category=row.get("Category", ""),
                size=row.get("Size", "NOT DEFINED"),
                area_code=row.get("Area Code", "-"),
                serial_no=str(row.get("Serial No", "")),
                series_code=row.get("Series Code", "-"),
                fluid_code=row.get("Fluid Code", ""),
                piping_class=row.get("Piping Class", ""),
                qty=int(row.get("Qty", 1) or 1),
                motor_actuator=row.get("Motor Actuator", "-"),
                # Handle trailing-space column name from validator.py
                pneumatic_actuator=row.get("Pneumatic Actuator ", row.get("Pneumatic Actuator", "-")),
                solenoid=row.get("Solenoid", "-"),
                line=row.get("line", ""),
            )
            db.add(valve)
    db.commit()
