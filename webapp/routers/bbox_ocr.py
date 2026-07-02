"""Per-bbox OCR tagging via Vision API.

Strategy:
  Instrument symbol circles (inst_field, inst_bpcs, inst_sis) contain the
  engineering tag printed INSIDE the circle split across 2-3 lines:
      62
      PDIT
      151022
  → tag = 62-PDIT-151022

  We OCR these circles directly with a tight crop (no wide padding that would
  pull in neighbouring instruments).  The matched entity_id is assigned to
  that very detection — no propagation to another bbox.

  Valve symbols (valve_bv, valve_db, valve_bf, valve_ck, valve_gl, valve_gt,
  valve_cv, valve_gen …) carry their tag printed OUTSIDE the symbol — beside,
  above, or below it.  We send the full tile image once per tile that has >=1
  valve detection, ask the model to return ALL engineering tags with their
  pixel centres, then proximity-match each valve centre to the nearest returned
  tag within _VALVE_TAG_PROXIMITY_PX.  Falls back to FIFO entity_id if no tag
  is close enough.

Endpoint: GET /api/v1/jobs/{job_id}/detections-tagged
"""

import base64
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from PIL import Image
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user, get_user_from_api_key
from webapp.config import get_job_dir
from webapp.database import get_db, SessionLocal
from webapp.deliverables.job_loader import JobCanonicalNotFound, load_canonical_for_job
from webapp.ocr_gate import mark_ocr_pending
from webapp.routers.api_v1 import _normalize_detection_shape, _attach_entity_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["bbox-ocr"])

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")

# Instrument circle labels — tag text is printed INSIDE these bboxes
_INSTRUMENT_LABELS = {"inst_field", "inst_bpcs", "inst_sis"}

# Small pad so the circle edge is fully visible but no neighbouring text leaks in
_CROP_PAD = 20

# Accepts both two-segment (AIT-3014, PG-3095A) and three-segment (62-PDIT-151022) tags.
# Optional leading unit prefix: (\d+-)?
# Instrument type: 2-8 uppercase letters
# Number part: one or more digits, optionally followed by 1-2 uppercase letters (AIT-400X, PG-3095A)
_TAG_RE = re.compile(r'^(\d+-)?[A-Z]{2,8}-\d+[A-Z]{0,2}$')


def _get_api_user(
    current_user: models.User = Depends(get_current_user),
    api_key_user: Optional[models.User] = Depends(get_user_from_api_key),
) -> models.User:
    return api_key_user or current_user


def _openrouter_client() -> Optional[OpenAI]:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    # Bound each OCR call (default OpenAI client timeout is 600s). The tile/circle
    # OCR calls sometimes fail or stall; without a tight timeout a stalled call
    # would hold a threadpool worker for 10 minutes (FEATURES #120).
    return OpenAI(api_key=key, base_url=OPENROUTER_BASE_URL, timeout=30.0, max_retries=1)


def _find_tile(job_dir: Path, tile_name: str) -> Optional[Path]:
    for base in (job_dir / "tmp", job_dir):
        p = base / tile_name
        if p.exists():
            return p
    return None


def _crop_b64(tile_path: Path, bbox: List[float], pad: int) -> Optional[str]:
    try:
        with Image.open(str(tile_path)) as img:
            W, H = img.size
            x1, y1, x2, y2 = bbox
            cx1 = max(0, int(x1) - pad)
            cy1 = max(0, int(y1) - pad)
            cx2 = min(W, int(x2) + pad)
            cy2 = min(H, int(y2) + pad)
            buf = io.BytesIO()
            img.crop((cx1, cy1, cx2, cy2)).save(buf, format="PNG")
            return base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.warning("crop failed for %s: %s", tile_path.name, e)
        return None


def _ocr_instrument_circle(client: OpenAI, img_b64: str) -> Optional[str]:
    """Read the engineering tag printed inside an instrument circle."""
    try:
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            max_tokens=24,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": (
                        "This image shows a single instrument circle from a P&ID engineering drawing. "
                        "Inside the circle, the engineering tag is printed on 2-3 lines like:\n"
                        "  62\n"
                        "  PDIT\n"
                        "  151022\n"
                        "Read the text inside this circle and return the complete tag as: 62-PDIT-151022\n\n"
                        "Other examples: 62-PZA-151023, 62-PZIT-151027, 62-HS-151014, 62-FI-151010\n\n"
                        "Return ONLY the tag string (digits-LETTERS-digits). "
                        "If the text is unclear, return: null"
                    )},
                ],
            }],
        )
        raw = (resp.choices[0].message.content or "").strip().strip('"\'').upper()
        if raw in ("NULL", "NONE", ""):
            return None
        # Normalise spacing/underscores that OCR sometimes inserts
        raw = raw.replace(" ", "-").replace("_", "-")
        while "--" in raw:
            raw = raw.replace("--", "-")
        if not _TAG_RE.match(raw):
            logger.debug("rejected non-tag response: %r", raw)
            return None
        return raw
    except Exception as e:
        logger.warning("Vision API call failed: %s", e)
        return None


def _run_ocr(job: models.Job, detections: list, entities: list) -> list:
    client = _openrouter_client()
    if not client:
        logger.warning("OPENROUTER_API_KEY not set — skipping OCR")
        return detections

    try:
        job_dir = (
            Path(job.output_csv_path).parent
            if getattr(job, "output_csv_path", None)
            else Path(get_job_dir(job))
        )
    except Exception:
        return detections

    # Case-insensitive tag → entity lookup
    tag_to_entity = {e.tag.upper(): e for e in entities if e.tag}

    enriched = []
    ocr_count = 0
    match_count = 0

    for det in detections:
        det = dict(det)
        label = det.get("label", "")

        # Only OCR instrument circles — they contain the tag text inside
        if label not in _INSTRUMENT_LABELS:
            enriched.append(det)
            continue

        bbox = det.get("bbox")
        tile_name = det.get("tile")
        if not bbox or not tile_name or len(bbox) != 4:
            enriched.append(det)
            continue

        tile_path = _find_tile(job_dir, tile_name)
        if not tile_path:
            enriched.append(det)
            continue

        img_b64 = _crop_b64(tile_path, bbox, _CROP_PAD)
        if not img_b64:
            enriched.append(det)
            continue

        ocr_count += 1
        tag = _ocr_instrument_circle(client, img_b64)
        logger.debug("[%s] %s → %s", label, tile_name, tag)

        if tag:
            ent = tag_to_entity.get(tag)
            if ent:
                det["entity_id"] = str(ent.entity_id)
                det["entity_tag"] = ent.tag
                det["entity_class"] = ent.entity_class
                match_count += 1
                logger.info("OCR: %s → %s", tag, ent.tag)
            else:
                # Tag read but not in canonical; expose it so the label still shows
                det["entity_id"] = None
                det["entity_tag"] = tag

        enriched.append(det)

    logger.info(
        "OCR complete: %d instrument circles processed, %d canonical matches",
        ocr_count, match_count,
    )
    return enriched


def _crop_valve_with_marker(tile_path: Path, bbox: List[float], context_px: int = 600) -> Optional[str]:
    """Crop a context window around a single valve and draw a red circle at its centre.

    Per-valve crops replace the whole-tile annotated approach because the LLM
    reliably confuses 8-10 numbered circles when they are packed together on a
    crowded tile — per-crop removes all ambiguity: there is exactly one valve
    in the image and exactly one red circle marks it.
    """
    try:
        from PIL import ImageDraw
        with Image.open(str(tile_path)) as img:
            img = img.convert("RGB")
            W, H = img.size
            x1, y1, x2, y2 = bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            cx0 = max(0, int(cx) - context_px)
            cy0 = max(0, int(cy) - context_px)
            cx1 = min(W, int(cx) + context_px)
            cy1 = min(H, int(cy) + context_px)
            crop = img.crop((cx0, cy0, cx1, cy1))
            draw = ImageDraw.Draw(crop)
            local_cx = int(cx) - cx0
            local_cy = int(cy) - cy0
            r = 20
            draw.ellipse([local_cx - r, local_cy - r, local_cx + r, local_cy + r],
                         outline="red", width=4)
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            return base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.warning("valve crop failed for %s: %s", tile_path.name, e)
        return None


def _ocr_single_valve_tag(client: OpenAI, crop_b64: str) -> Optional[str]:
    """Ask the LLM for the engineering tag of the one valve marked with a red circle."""
    try:
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            max_tokens=32,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{crop_b64}"}},
                    {"type": "text", "text": (
                        "This image is a crop from a P&ID engineering drawing centred on a single "
                        "valve symbol, which is marked with a RED CIRCLE.\n\n"
                        "Find the engineering tag printed alongside the pipe near the red circle. "
                        "Tags follow patterns like: 62-BV-151001, 62-DB-151022, 62-CK-151012, "
                        "62-BF-151031. The text is often printed VERTICALLY (rotated 90°) along "
                        "the pipe, or horizontally near the valve symbol.\n\n"
                        "Return ONLY the tag string (e.g. 62-BV-151001). "
                        "If no tag is visible, return: null"
                    )},
                ],
            }],
        )
        raw = (resp.choices[0].message.content or "").strip().strip('"\'').upper()
        if raw in ("NULL", "NONE", ""):
            return None
        raw = raw.replace(" ", "-").replace("_", "-")
        while "--" in raw:
            raw = raw.replace("--", "-")
        if not _TAG_RE.match(raw):
            logger.debug("rejected non-tag valve response: %r", raw)
            return None
        return raw
    except Exception as e:
        logger.warning("Single valve OCR failed: %s", e)
        return None


def _run_valve_ocr(job: models.Job, detections: list, entities: list) -> list:
    """Assign entity_ids to valve detections using per-valve crop OCR.

    For each valve detection we crop a 600 px context window from its tile,
    draw a single red circle at the valve centre, and ask the LLM for the ONE
    tag associated with that valve.  One API call per valve eliminates the
    cyclic mis-assignment that occurred when the LLM tried to map 8-10 numbered
    circles on a crowded tile all in one shot.
    """
    client = _openrouter_client()
    if not client:
        return detections

    try:
        job_dir = (
            Path(job.output_csv_path).parent
            if getattr(job, "output_csv_path", None)
            else Path(get_job_dir(job))
        )
    except Exception:
        return detections

    tag_to_entity = {e.tag.upper(): e for e in entities if e.tag}

    enriched = [dict(d) for d in detections]
    total_valves = 0
    total_matched = 0

    for idx, det in enumerate(enriched):
        if not det.get("label", "").startswith("valve_"):
            continue
        bbox = det.get("bbox")
        tile_name = det.get("tile")
        if not bbox or len(bbox) != 4 or not tile_name:
            continue

        tile_path = _find_tile(job_dir, tile_name)
        if not tile_path:
            continue

        crop_b64 = _crop_valve_with_marker(tile_path, bbox)
        if not crop_b64:
            continue

        total_valves += 1
        tag_str = _ocr_single_valve_tag(client, crop_b64)
        logger.debug("[valve] %s bbox=%s → %s", tile_name, bbox, tag_str)

        if not tag_str:
            det["entity_id"] = None
            det["entity_tag"] = None
            continue

        ent = tag_to_entity.get(tag_str)
        if ent:
            det["entity_id"] = str(ent.entity_id)
            det["entity_tag"] = ent.tag
            det["entity_class"] = ent.entity_class
            total_matched += 1
            logger.info("Valve OCR: %s → %s", tag_str, ent.tag)
        else:
            # Tag read but not in canonical — expose the raw tag so the canvas
            # label still shows what the LLM saw, but no entity linkage.
            det["entity_id"] = None
            det["entity_tag"] = tag_str

    logger.info(
        "Valve OCR complete: %d valves OCR'd, %d canonical matches",
        total_valves, total_matched,
    )
    return enriched


def _cache_path(job: models.Job) -> Optional[Path]:
    try:
        if getattr(job, "output_csv_path", None):
            return Path(job.output_csv_path).parent / "detections_ocr.json"
        return Path(get_job_dir(job)) / "detections_ocr.json"
    except Exception:
        return None


def _parse_raw_detections(job: models.Job) -> list:
    """Best-effort decode of Job.gpu_detections into a list (empty on any error)."""
    if not job.gpu_detections:
        return []
    try:
        parsed = json.loads(job.gpu_detections)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _promote_orphan_detections(job: models.Job, enriched: list, canonical: "JobCanonical") -> "JobCanonical":
    """Promote detections that have an OCR-read entity_tag but no entity_id into canonical.json.

    These are instruments/valves that YOLO found and OCR tagged but OpenRouter
    missed during extraction. After promotion they appear in the sidebar, bulk
    review, and all deliverables exactly like any other entity.

    Returns the updated JobCanonical (unchanged if no orphans found).
    """
    from uuid import uuid4
    from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
    from webapp.taxonomy import yolo_to_canonical

    existing_tags = {e.tag.upper() for e in canonical.entities if e.tag}
    pid_number = canonical.entities[0].pid_number if canonical.entities else (job.pid_no or "UNKNOWN")

    seen: set = set()
    new_entities = []

    for det in enriched:
        tag = det.get("entity_tag")
        if not tag or det.get("entity_id"):
            continue
        key = tag.upper()
        if key in existing_tags or key in seen:
            continue
        seen.add(key)

        label = det.get("label", "")
        entity_class, sub_class = yolo_to_canonical(label)
        if not entity_class:
            entity_class = "instrument"

        # For instruments derive sub_class from the type code in the tag
        # (e.g. "62-FT-151008" → type_code = "FT")
        if entity_class == "instrument" and not sub_class:
            parts = tag.split("-")
            # Three-segment tag: unit-TYPE-number  (e.g. 62-FT-151008)
            # Two-segment tag:   TYPE-number       (e.g. FT-151008)
            if len(parts) == 3:
                sub_class = parts[1].upper()
            elif len(parts) == 2:
                sub_class = parts[0].upper()
            else:
                sub_class = label.upper() or "INSTRUMENT"

        if not sub_class:
            sub_class = label.upper() or "UNKNOWN"

        new_entities.append(CanonicalEntity(
            entity_id=uuid4(),
            entity_class=entity_class,
            sub_class=sub_class,
            tag=tag,
            pid_number=pid_number,
            sheet_number=1,
            bbox=(0.0, 0.0, 0.0, 0.0),
            fields={},
        ))

    if not new_entities:
        return canonical

    updated = JobCanonical(
        job_id=canonical.job_id,
        canonical_schema_version=canonical.canonical_schema_version,
        customer_template_slug=canonical.customer_template_slug,
        entities=list(canonical.entities) + new_entities,
    )

    try:
        canonical_path = Path(job.output_csv_path).parent / "canonical.json"
        canonical_path.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Promoted %d orphan detections into canonical for job %d", len(new_entities), job.id)
    except Exception as e:
        logger.warning("Failed to write updated canonical for job %d: %s", job.id, e)
        return canonical

    # Back-fill entity_ids into the enriched detections list so the canvas
    # immediately renders them as solid (matched) bboxes without a second pass.
    tag_to_eid = {e.tag.upper(): (str(e.entity_id), e.entity_class) for e in new_entities}
    for det in enriched:
        tag = det.get("entity_tag")
        if tag and not det.get("entity_id"):
            k = tag.upper()
            if k in tag_to_eid:
                det["entity_id"], det["entity_class"] = tag_to_eid[k]

    return updated


def compute_tagged_detections(job: models.Job) -> dict:
    """Run the full OCR pipeline for a job and write the cache. Returns the
    result dict. Always recomputes (it is the background job's whole point) and
    overwrites the cache, so there is no `refresh` flag here.

    This is the EXPENSIVE half (one Vision call per instrument circle + one per
    tile with valves). It runs on the cpu-worker via :func:`run_detections_ocr_rq`,
    NOT inline on the web request — the GET endpoint only enqueues it.
    """
    cache = _cache_path(job)

    raw_dets = _parse_raw_detections(job)
    if not raw_dets:
        result = {"detections": [], "ocr_run": False, "ocr_status": "empty"}
        if cache:
            try:
                cache.write_text(json.dumps(result))
            except Exception as e:
                logger.warning("Failed to write empty OCR cache: %s", e)
        return result

    _normalize_detection_shape(raw_dets)

    # Drop cross-tile duplicate detections (3x3 tiles, 20% overlap) BEFORE
    # matching/OCR — cleans the cache, makes matching 1:1, cuts OCR calls.
    from webapp.graph.page_geometry import page_dims_for_job
    from webapp.graph.loader import compute_tile_offsets
    from webapp.graph.detection_dedup import dedupe_detections_page_space, enforce_one_to_one
    _dims = page_dims_for_job(job)
    if _dims:
        _offs = compute_tile_offsets(_dims[0], _dims[1], 0)
        raw_dets = dedupe_detections_page_space(raw_dets, _offs)

    canonical = None
    entities = []
    if job.output_csv_path:
        try:
            canonical = load_canonical_for_job(job.output_csv_path)
            entities = canonical.entities
        except JobCanonicalNotFound:
            pass

    # Apply standard FIFO matching first (gives valves their entity_ids)
    _attach_entity_ids(raw_dets, entities)

    # Override instrument circles with OCR-accurate tags (circle text inside)
    enriched = _run_ocr(job, raw_dets, entities)

    # Override valve entity_ids using tile-level OCR + proximity matching
    enriched = _run_valve_ocr(job, enriched, entities)

    enforce_one_to_one(enriched)

    # Promote orphan detections (OCR tag found, not in canonical) into canonical.json
    # so they appear in the sidebar, bulk review, and all deliverables.
    if canonical is not None and job.output_csv_path:
        try:
            canonical = _promote_orphan_detections(job, enriched, canonical)
            try:
                from webapp.deliverables.canonical_db_index import sync_canonical_to_db
                from webapp.database import SessionLocal
                _db = SessionLocal()
                sync_canonical_to_db(canonical, _db)
                _db.commit()
                _db.close()
            except Exception as _sync_err:
                logger.warning("DB index sync after orphan promotion failed for job %d: %s", job.id, _sync_err)
        except Exception as _promo_err:
            logger.warning("Orphan promotion failed for job %d: %s", job.id, _promo_err)

    result = {
        "detections": enriched,
        "ocr_run": True,
        "valve_ocr_run": True,
        "ocr_status": "ready",
    }
    if cache:
        try:
            cache.write_text(json.dumps(result, default=str))
        except Exception as e:
            logger.warning("Failed to write OCR cache: %s", e)

    return result


def run_detections_ocr_rq(job_id: int) -> dict:
    """RQ entry-point (runs on cpu-worker). Loads the job, computes tags, caches.

    On failure, persist ocr_status="done" before re-raising so the dashboard gate
    releases immediately (graceful degradation — detections just lack OCR tags)
    rather than trapping the card at "Preparing". Re-raising preserves RQ failure
    observability (the RQ job still records as failed, and RQ retries once).
    """
    db = SessionLocal()
    try:
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if not job:
            logger.warning("OCR job %s no longer exists — skipping", job_id)
            return {"detections": [], "ocr_run": False, "ocr_status": "empty"}
        try:
            result = compute_tagged_detections(job)
        except Exception as e:
            logger.warning("OCR job %s failed (%s) — releasing gate to done", job_id, e)
            job.ocr_status = "done"
            db.commit()
            raise
        # Mark OCR done so the dashboard can show "Done" status
        job.ocr_status = "done"
        db.commit()
        return result
    finally:
        db.close()


def _enqueue_detections_ocr(job_id: int) -> None:
    """Enqueue the OCR pipeline on the cpu queue, deduped by a deterministic RQ
    job id so a burst of page-loads collapses to one running job.

    If a *terminal* job (finished/failed/stopped) still holds the id within its
    result_ttl, we delete it first — otherwise enqueuing with the same job_id
    raises "job already exists", which would silently drop an explicit recompute
    (refresh) for up to result_ttl seconds.
    """
    try:
        from webapp.queue import get_cpu_queue
        from rq.job import Job as RQJob
        from rq.exceptions import NoSuchJobError
        from rq import Retry

        q = get_cpu_queue()
        rq_id = f"detections-ocr-{job_id}"
        try:
            existing = RQJob.fetch(rq_id, connection=q.connection)
            status = existing.get_status(refresh=True)
            if status in ("queued", "started", "deferred", "scheduled"):
                logger.info("OCR job %s already %s — not re-enqueuing", job_id, status)
                return
            # Terminal state — free the id so the same-id enqueue below succeeds.
            existing.delete()
        except NoSuchJobError:
            pass

        q.enqueue(
            "webapp.routers.bbox_ocr.run_detections_ocr_rq",
            job_id,
            job_id=rq_id,
            job_timeout=900,
            result_ttl=300,
            retry=Retry(max=1),  # absorb a transient worker-kill (deploy) mid-run
        )
        logger.info("Enqueued background OCR for job %s", job_id)
        # Mark pending + stamp enqueue time so the dashboard holds "Done" until
        # OCR finishes and the stale-gate timeout has a reference point.
        try:
            db = SessionLocal()
            job = db.query(models.Job).filter(models.Job.id == job_id).first()
            if job and job.ocr_status != "done":
                mark_ocr_pending(job)
                db.commit()
            db.close()
        except Exception:
            pass
    except Exception as e:
        # If the queue is unreachable, don't 500 the page — the client will
        # simply keep its plain (un-OCR'd) detections.
        logger.warning("Failed to enqueue OCR for job %s: %s", job_id, e)


@router.get("/jobs/{job_id}/detections-tagged")
def api_job_detections_tagged(
    job_id: int,
    refresh: bool = False,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """Return OCR-tagged detections if cached; otherwise enqueue the OCR
    pipeline on the cpu-worker and return immediately with ocr_status="pending".

    The OCR work (one Vision call per instrument circle + one per tile) used to
    run inline on this GET, blocking the request for ~40 API calls and able to
    saturate the threadpool under a burst. It now runs in the background
    (FEATURES #122); the client polls this endpoint until ocr_status != "pending".

    Response shape:
      - ocr_status="ready"   → detections include OCR-resolved entity tags.
      - ocr_status="empty"   → job has no detections to OCR (terminal).
      - ocr_status="pending" → background job enqueued/running; poll again.
    """
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Access denied")

    cache = _cache_path(job)
    if cache and cache.exists() and not refresh:
        try:
            cached = json.loads(cache.read_text())
            # Only serve cache if valve OCR has already been run on it;
            # old caches (pre-valve-OCR) lack this key and must be regenerated.
            if cached.get("valve_ocr_run"):
                cached.setdefault("ocr_status", "ready")
                # For detections that have an OCR'd entity_tag but no entity_id
                # (i.e. the tag wasn't in canonical when OCR ran — e.g. pipeline
                # rerun added new instruments), resolve them against the current
                # canonical without touching detections that already have correct
                # entity_ids (avoids FIFO collisions).
                if job.output_csv_path:
                    try:
                        from webapp.deliverables.job_loader import load_canonical_for_job
                        canonical = load_canonical_for_job(job.output_csv_path)
                        tag_to_eid = {
                            e.tag.upper(): (str(e.entity_id), e.entity_class)
                            for e in canonical.entities if e.tag
                        }
                        for det in cached.get("detections", []):
                            if det.get("entity_tag") and not det.get("entity_id"):
                                key = det["entity_tag"].upper()
                                if key in tag_to_eid:
                                    det["entity_id"], det["entity_class"] = tag_to_eid[key]
                        # The backfill above re-binds by tag without consuming;
                        # re-enforce 1:1 so one entity isn't bound to multiple
                        # detections (tile-duplicates / a BPCS+SIS sharing a tag
                        # would otherwise all light up on selection).
                        from webapp.graph.detection_dedup import enforce_one_to_one
                        enforce_one_to_one(cached.get("detections", []))
                    except Exception:
                        pass
                return cached
            # An "empty" terminal cache is also safe to serve as-is.
            if cached.get("ocr_status") == "empty":
                return cached
        except Exception:
            pass

    # Nothing to OCR → answer instantly (and cache the terminal empty result).
    if not _parse_raw_detections(job):
        result = {"detections": [], "ocr_run": False, "ocr_status": "empty"}
        if cache:
            try:
                cache.write_text(json.dumps(result))
            except Exception:
                pass
        return result

    # Heavy work goes to the background worker; client polls until ready.
    # (refresh only matters for the cache-serve decision above; the background
    # job always recomputes and overwrites the cache.)
    _enqueue_detections_ocr(job_id)
    return {"detections": [], "ocr_run": False, "ocr_status": "pending"}
