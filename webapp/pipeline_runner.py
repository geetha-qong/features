"""
Adapter: runs the existing pipeline.run() in a per-job directory,
then stores results in the database.
"""
import csv
import io
import json
import os
import re
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
from webapp.datetime_utils import utc_iso
from webapp.deliverables.pipeline_emitter import write_canonical_for_job

_pipeline_lock = threading.Lock()

# Heartbeat cadence — every N seconds the heartbeat thread refreshes
# last_heartbeat_at + current_stage on the JobRun row. The watchdog
# considers a run stale if no heartbeat for > 3× this interval.
HEARTBEAT_INTERVAL_SECONDS = 30

# Matches the "Stage N: …" headers that pipeline.run() prints. We grep the
# captured stdout for the latest of these to populate JobRun.current_stage.
_STAGE_LINE_RE = re.compile(r"^Stage\s+(\w+):\s*(.+?)(?:\.\.\.)?\s*$", re.MULTILINE)

# Add project root to sys.path so pipeline imports work
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _short_session():
    """Open a transient session — used for short DB writes around the pipeline run."""
    from webapp.database import SessionLocal
    return SessionLocal()


def _latest_stage(log_text: str) -> str:
    """Return the most-recent 'Stage N: ...' line in the captured pipeline log."""
    matches = _STAGE_LINE_RE.findall(log_text)
    if not matches:
        return ""
    n, label = matches[-1]
    return f"Stage {n}: {label.strip()}"


def _create_job_run(job_id: int, rq_id: str) -> int:
    """Create a JobRun row for this attempt and return its id."""
    db = _short_session()
    try:
        prev = (
            db.query(models.JobRun)
            .filter(models.JobRun.job_id == job_id)
            .order_by(models.JobRun.attempt_num.desc())
            .first()
        )
        attempt_num = (prev.attempt_num + 1) if prev else 1
        run = models.JobRun(
            job_id=job_id,
            attempt_num=attempt_num,
            rq_id=rq_id or None,
            started_at=datetime.utcnow(),
            status="running",
            last_heartbeat_at=datetime.utcnow(),
            stage_timings=json.dumps([]),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def _finalize_job_run(run_id: int, status: str, error_msg: str = "", error_traceback: str = "") -> None:
    """Write the terminal state of a JobRun in its own short-lived session."""
    db = _short_session()
    try:
        run = db.query(models.JobRun).filter(models.JobRun.id == run_id).first()
        if not run:
            return
        run.status = status
        run.ended_at = datetime.utcnow()
        if error_msg:
            run.error_msg = error_msg
        if error_traceback:
            run.error_traceback = error_traceback
        db.commit()
    finally:
        db.close()


class _HeartbeatThread(threading.Thread):
    """Background thread: every HEARTBEAT_INTERVAL_SECONDS, refreshes the
    JobRun's last_heartbeat_at and current_stage from the captured stdout.
    Also records stage-transition timings into JobRun.stage_timings (JSON).

    Uses its own short-lived session per beat so it never holds a
    transaction open across the pipeline run.
    """

    def __init__(self, run_id: int, log_buffer: io.StringIO):
        super().__init__(daemon=True, name=f"jobrun-heartbeat-{run_id}")
        self.run_id = run_id
        self.log_buffer = log_buffer
        self._stop_event = threading.Event()
        self._current_stage: str = ""
        self._stage_started_at: datetime = datetime.utcnow()
        self._stage_timings: list = []

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        # Emit one beat immediately so last_heartbeat_at is fresh from the start.
        self._beat()
        while not self._stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            self._beat()

    def _beat(self) -> None:
        now = datetime.utcnow()
        try:
            stage = _latest_stage(self.log_buffer.getvalue())
        except Exception:
            stage = self._current_stage
        # Stage transition → close the previous stage's timing window
        if stage and stage != self._current_stage:
            if self._current_stage:
                self._stage_timings.append({
                    "stage": self._current_stage,
                    "started_at": utc_iso(self._stage_started_at),
                    "ended_at": utc_iso(now),
                })
            self._current_stage = stage
            self._stage_started_at = now

        db = _short_session()
        try:
            run = db.query(models.JobRun).filter(models.JobRun.id == self.run_id).first()
            if not run:
                return
            run.last_heartbeat_at = now
            if self._current_stage:
                run.current_stage = self._current_stage
            run.stage_timings = json.dumps(self._stage_timings)
            db.commit()
        except Exception:
            # Heartbeat must never crash the worker. Swallow and retry next beat.
            pass
        finally:
            db.close()


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
    output_annotated_pdf = str(job_dir / "annotated.pdf")

    # ── 1b. Open a JobRun row for this attempt + start the heartbeat thread ──
    try:
        from rq import get_current_job as _rq_get_current_job
        _rq_job = _rq_get_current_job()
        _rq_id = _rq_job.id if _rq_job else ""
    except Exception:
        _rq_id = ""
    run_id = _create_job_run(job_id, _rq_id)

    # ── 2. Run the pipeline with NO open DB session ──
    log_buffer = io.StringIO()
    heartbeat = _HeartbeatThread(run_id=run_id, log_buffer=log_buffer)
    heartbeat.start()
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
                    annotated_pdf_path=output_annotated_pdf,
                    original_filename=original_filename,
                )
    except Exception:
        pipeline_error = traceback.format_exc()
    finally:
        os.chdir(original_cwd)
        heartbeat.stop()
        # Don't join — the thread is a daemon and we don't want to block
        # the worker shutting down on a final heartbeat round-trip.

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
            _finalize_job_run(run_id, "failed", error_msg="pipeline exception", error_traceback=pipeline_error)
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
            _tb = traceback.format_exc()
            job.status = "failed"
            job.error_msg = f"CSV ingest error: {_tb}"
            job.processing_time = elapsed
            job.processing_log = log_text
            job.completed_at = datetime.utcnow()
            db.commit()
            _finalize_job_run(run_id, "failed", error_msg="CSV ingest error", error_traceback=_tb)
            return

        job.status = "done"
        job.output_csv_path = output_csv
        if Path(output_inst_index).exists():
            job.output_inst_index_path = output_inst_index
        if Path(output_inst_datasheets).exists():
            job.output_inst_datasheet_path = output_inst_datasheets
        if Path(output_annotated_pdf).exists():
            job.output_annotated_pdf_path = output_annotated_pdf
        job.completed_at = datetime.utcnow()
        job.processing_time = elapsed
        job.processing_log = log_text
        job.valve_count = (
            db.query(models.ValveRow).filter(models.ValveRow.job_id == job_id).count()
        )
        db.commit()

        # Emit canonical.json so the deliverables export endpoint can serve this job
        # (Plan A.5 #11). Failures here are non-fatal — pipeline state stays "done".
        # Also dual-write into the `canonical_entities` table (FEATURES #34) so
        # admin dashboards + cross-job queries don't need to parse N JSON files.
        # DB sync failures are likewise non-fatal — the JSON is the source of truth.
        try:
            from webapp.deliverables.canonical_db_index import sync_canonical_to_db
            from webapp.deliverables.job_loader import load_canonical_for_job

            write_canonical_for_job(job_dir=job_dir, job_id=job_id)
            try:
                canonical = load_canonical_for_job(str(job_dir / "valve_list.csv"))
                ins, upd = sync_canonical_to_db(canonical, db)
                print(f"[canonical-db] job {job_id}: inserted={ins} updated={upd}")
            except Exception as _db_err:
                print(f"[canonical-db] job {job_id}: {_db_err}", file=sys.stderr)
        except Exception as _emit_err:
            print(f"[canonical-emit] job {job_id}: {_emit_err}", file=sys.stderr)

        # In-process YOLO inference for canvas bbox surfacing (FEATURES #28).
        # Populates Job.gpu_detections so the SPA studio canvas gets overlays
        # without depending on the Windows GPU worker callback. Non-fatal —
        # CSV/deliverables are the headline product; bbox overlays are gravy.
        try:
            _run_inplace_inference(job_id, job_dir)
        except Exception as _yolo_err:
            print(f"[inplace-yolo] job {job_id}: {_yolo_err}", file=sys.stderr)

        # Graph extraction (2026-06-13 design). Build canonical_graph.json from
        # the full-page image + canonical entities + YOLO detections, then
        # dual-write the graph_nodes/graph_edges read-index. Runs AFTER in-place
        # inference so Job.gpu_detections is populated. gpu_detections bboxes are
        # TILE-LOCAL (inference.py), so pass tile_local_detections=True to
        # translate to page-pixel. Non-fatal — a graph failure logs but never
        # rolls back job "done" (same contract as the canonical-db sync above).
        try:
            from webapp.graph.pipeline import extract_graph
            from webapp.graph.graph_db_index import sync_graph_to_db
            from webapp.datetime_utils import utc_iso, utcnow

            db.refresh(job)
            raw_dets = job.gpu_detections
            detections = json.loads(raw_dets) if isinstance(raw_dets, str) and raw_dets else (raw_dets or [])
            if detections:
                graph = extract_graph(
                    str(job_dir),
                    detections,
                    generated_at=utc_iso(utcnow()),
                    job_id=job_id,
                    tile_local_detections=True,
                )
                n_nodes, n_edges = sync_graph_to_db(graph, db)
                _stats = graph.get("stats", {})
                print(f"[graph-extract] job {job_id}: nodes={n_nodes} edges={n_edges} "
                      f"fallback={_stats.get('fallback_used')}")
            else:
                print(f"[graph-extract] job {job_id}: no detections — skipped")
        except Exception as _g_err:
            print(f"[graph-extract] job {job_id}: {_g_err}", file=sys.stderr)

        _finalize_job_run(run_id, "done")

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


def _run_inplace_inference(job_id: int, job_dir: Path) -> None:
    """Run YOLO ONNX inference on all tiles and write to Job.gpu_detections.

    FEATURES #28. This is the in-process counterpart to
    :func:`_dispatch_gpu_job` — both write the same shape into the same DB
    column. The GPU worker is faster on its CUDA box; this CPU path is the
    default everywhere else (on-prem deploys, CI, local dev).

    Skipped automatically when ``gpu_detections`` already has content — the
    GPU worker callback wins if it raced ahead.
    """
    from webapp.inference import run_yolo_inference, InferenceError

    tile_files = sorted((job_dir / "tmp").glob("tile_p*_r*_c*.png"))
    if not tile_files:
        return

    db = _short_session()
    try:
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if not job:
            return
        # Don't clobber a real GPU-worker result that already landed.
        if job.gpu_detections:
            try:
                existing = json.loads(job.gpu_detections)
                if isinstance(existing, list) and len(existing) > 0:
                    print(f"[inplace-yolo] job {job_id}: gpu_detections already populated ({len(existing)}); skipping")
                    return
            except (ValueError, TypeError):
                pass  # fall through and overwrite garbage

        try:
            detections = run_yolo_inference(tile_files)
        except InferenceError as exc:
            # Expected mode: model missing on dev machines without the
            # baked image. Log and exit cleanly.
            print(f"[inplace-yolo] job {job_id}: {exc}")
            return

        job.gpu_detections = json.dumps(detections)
        db.commit()
        print(f"[inplace-yolo] job {job_id}: stored {len(detections)} detections")
    finally:
        db.close()


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
