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


def _short_session():
    """Open a transient session — used for short DB writes around the pipeline run."""
    from webapp.database import SessionLocal
    return SessionLocal()


def run_pipeline_for_job_rq(
    job_id: int,
    pdf_path: str,
    pid_no_override: str = "",
    include_control_valves: bool = True,
    original_filename: str = "",
) -> None:
    """RQ-callable entrypoint. Manages its own short-lived DB sessions so the
    long-running pipeline never holds a transaction open against the database.
    """
    # ── 1. Set status='processing', resolve job paths, then close the session ──
    db = _short_session()
    try:
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if not job:
            return
        job.status = "processing"
        db.commit()
        job_dir = get_job_dir(job)
    finally:
        db.close()

    job_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = job_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    output_csv = str(job_dir / "valve_list.csv")
    output_inst_index = str(job_dir / "instrumentation_index.csv")
    output_inst_datasheets = str(job_dir / "instrument_datasheets.zip")

    # ── 2. Run the pipeline with NO open DB session ──
    log_buffer = io.StringIO()
    start_time = time.time()
    pipeline_error: str = ""
    original_cwd = os.getcwd()
    try:
        with _pipeline_lock:
            os.chdir(str(job_dir))
            Path("tmp").mkdir(exist_ok=True)
            import importlib
            import pipeline as pl
            importlib.reload(pl)
            with redirect_stdout(log_buffer):
                pl.run(
                    pdf_path=pdf_path,
                    output_path=output_csv,
                    inst_output_path=output_inst_index,
                    datasheet_zip_path=output_inst_datasheets,
                    original_filename=original_filename,
                )
    except Exception:
        pipeline_error = traceback.format_exc()
    finally:
        os.chdir(original_cwd)

    elapsed = round(time.time() - start_time, 1)
    log_text = log_buffer.getvalue()

    # ── 3. Open a fresh session and write the final state ──
    db = _short_session()
    try:
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if not job:
            return

        if pipeline_error:
            job.status = "failed"
            job.error_msg = pipeline_error
            job.processing_time = elapsed
            job.processing_log = log_text
            job.completed_at = datetime.utcnow()
            db.commit()
            return

        # If pid_no wasn't provided, read it from the valve CSV
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
            except Exception:
                pass  # non-fatal, keep whatever the row had

        # Insert valve rows from the CSV
        try:
            _ingest_csv(job_id, output_csv, pid_no_override, db, include_control_valves)
        except Exception:
            job.status = "failed"
            job.error_msg = f"CSV ingest error: {traceback.format_exc()}"
            job.processing_time = elapsed
            job.processing_log = log_text
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
        job.processing_time = elapsed
        job.processing_log = log_text
        job.valve_count = (
            db.query(models.ValveRow).filter(models.ValveRow.job_id == job_id).count()
        )
        db.commit()

        # Side effects (LS sync, GPU dispatch) use the same session
        _auto_sync_to_label_studio(job, job_dir, db)
        _dispatch_gpu_job(job, job_dir)
    finally:
        db.close()


def _auto_sync_to_label_studio(job, job_dir: Path, db) -> None:
    """Push job tiles to Label Studio automatically after pipeline completes."""
    from webapp import label_studio_client as ls
    if not ls.is_configured():
        return
    try:
        tile_files = sorted((job_dir / "tmp").glob("tile_p*_r*_c*.png"))
        if not tile_files:
            return
        # Use WEBAPP_BASE_URL env var (set to public domain on GCP, defaults to internal Docker URL)
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


def _dispatch_gpu_job(job, job_dir: Path) -> None:
    """Enqueue YOLO inference on the GPU RQ queue after tiles are generated.

    Requires GPU_CALLBACK_SECRET and GPU queue reachable (Tailscale Redis).
    No-ops silently if not configured — CPU pipeline result is unaffected.
    """
    import re
    callback_secret = os.environ.get("GPU_CALLBACK_SECRET", "")
    if not callback_secret:
        return

    tile_files = sorted((job_dir / "tmp").glob("tile_p*_r*_c*.png"))
    if not tile_files:
        return

    # GPU worker reaches the webapp via Tailscale (not the public domain)
    base_url = os.environ.get("GPU_INTERNAL_BASE_URL", "http://100.127.190.88:8000").rstrip("/")
    _tile_re = re.compile(r'tile_p(\d+)_r(\d+)_c(\d+)\.png')
    tile_infos = []
    for f in tile_files:
        m = _tile_re.match(f.name)
        if not m:
            continue
        tile_infos.append({
            "url": f"{base_url}/jobs/{job.id}/tiles/{f.name}",
            "row": int(m.group(2)),
            "col": int(m.group(3)),
            "page": int(m.group(1)),
            "x0": 0, "y0": 0,
        })

    if not tile_infos:
        return

    try:
        from webapp.queue import get_gpu_queue
        get_gpu_queue().enqueue(
            "worker.run_inference_job",
            kwargs={
                "job_id": job.id,
                "pid_no": job.pid_no or f"job-{job.id}",
                "tile_infos": tile_infos,
                "callback_url": f"{base_url}/api/v1/jobs/{job.id}/gpu-result",
                "api_key": callback_secret,
            },
            job_timeout=1800,
        )
        print(f"[gpu] Dispatched job {job.id} ({len(tile_infos)} tiles)")
    except Exception as e:
        print(f"[gpu] Dispatch error for job {job.id}: {e}")


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
