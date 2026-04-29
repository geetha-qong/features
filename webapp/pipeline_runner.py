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
from webapp.config import JOB_OUTPUT_DIR, get_job_dir

_pipeline_lock = threading.Lock()

# Add project root to sys.path so pipeline imports work
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def run_pipeline_for_job(job_id: int, pdf_path: str, pid_no_override: str, db: Session, include_control_valves: bool = True, original_filename: str = "") -> None:
    """
    Called in a background thread. Runs the pipeline and updates the DB.
    """
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        return

    job.status = "processing"
    db.commit()

    job_dir = get_job_dir(job)
    job_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = job_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    output_csv = str(job_dir / "valve_list.csv")
    output_inst_index = str(job_dir / "instrumentation_index.csv")
    output_inst_datasheets = str(job_dir / "instrument_datasheets.zip")

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
                pl.run(pdf_path=pdf_path, output_path=output_csv, inst_output_path=output_inst_index, datasheet_zip_path=output_inst_datasheets, original_filename=original_filename)

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

    # If pid_no was not provided by user, read it from the CSV (auto-extracted by pipeline)
    if not pid_no_override or pid_no_override == "UNKNOWN":
        try:
            with open(output_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                first_row = next(reader, None)
                if first_row:
                    extracted_pid = first_row.get("P&ID No", "").strip()
                    if extracted_pid and extracted_pid != "UNKNOWN":
                        pid_no_override = extracted_pid
                        job.pid_no = extracted_pid
                        db.commit()
        except Exception:
            pass  # non-fatal, keep UNKNOWN

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
    if Path(output_inst_index).exists():
        job.output_inst_index_path = output_inst_index
    if Path(output_inst_datasheets).exists():
        job.output_inst_datasheet_path = output_inst_datasheets
    job.completed_at = datetime.utcnow()
    job.processing_time = round(time.time() - start_time, 1)
    job.processing_log = log_buffer.getvalue()
    job.valve_count = db.query(models.ValveRow).filter(models.ValveRow.job_id == job_id).count()
    db.commit()

    # Auto-sync tiles to Label Studio if configured
    _auto_sync_to_label_studio(job, job_dir, db)


def _auto_sync_to_label_studio(job, job_dir: Path, db) -> None:
    """Push job tiles to Label Studio automatically after pipeline completes."""
    from webapp import label_studio_client as ls
    if not ls.is_configured():
        return
    try:
        tile_files = sorted((job_dir / "tmp").glob("tile_p*_r*_c*.png"))
        if not tile_files:
            return
        # Use WEBAPP_BASE_URL env var (set to ngrok URL when sharing externally,
        # defaults to internal Docker URL so LS container can always reach tiles)
        base_url = os.environ.get("WEBAPP_BASE_URL", "http://web:8000").rstrip("/")
        tile_urls = [f"{base_url}/jobs/{job.id}/tiles/{f.name}" for f in tile_files]
        project_id = job.ls_project_id or ls.get_or_create_project(job.pid_no or f"job-{job.id}")
        if not project_id:
            return
        pushed = ls.push_tiles(project_id, tile_urls)
        job.ls_project_id = project_id
        job.ls_synced = pushed > 0
        db.commit()
        print(f"[label_studio] Auto-synced {pushed} tiles for job {job.id} → project {project_id}")
    except Exception as e:
        print(f"[label_studio] Auto-sync error for job {job.id}: {e}")


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
