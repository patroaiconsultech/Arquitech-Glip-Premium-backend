"""Run as a separate worker service after applying the Visual AI feature flag.

Example: PYTHONPATH=src python scripts/process_visual_ai_jobs.py
"""
from __future__ import annotations
import logging
import os
import time

from glip.config import settings
from glip.database import SessionLocal
from glip.models import ArtifactJob
from glip.visual_ai_worker import VisualAIError, claim_visual_job, process_visual_job

log = logging.getLogger("glip.visual-ai-worker")


def main() -> int:
    if not settings.visual_ai_enabled or settings.visual_ai_provider != "openai":
        raise SystemExit("VISUAL_AI_WORKER_DISABLED")
    if not settings.visual_ai_openai_api_key:
        raise SystemExit("VISUAL_AI_PROVIDER_KEY_REQUIRED")
    logging.basicConfig(level=logging.INFO)
    once = os.environ.get("GLIP_VISUAL_AI_WORKER_ONCE", "false").lower() == "true"
    idle = max(1.0, min(30.0, float(os.environ.get("GLIP_VISUAL_AI_WORKER_IDLE_SECONDS", "3"))))
    while True:
        with SessionLocal() as db:
            job_id = claim_visual_job(db)
            db.commit()
        if job_id:
            with SessionLocal() as db:
                try:
                    process_visual_job(db, settings=settings, job_id=job_id)
                    log.info("visual_job_completed job_id=%s", job_id)
                except Exception as exc:
                    db.rollback()
                    job = db.get(ArtifactJob, job_id)
                    if job is not None and job.status == "processing":
                        job.status = "failed"
                        job.error_code = str(exc)[:120] if isinstance(exc, VisualAIError) else "VISUAL_INTERNAL_ERROR"
                        db.commit()
                    log.error("visual_job_failed job_id=%s error_code=%s",
                              job_id, "VISUAL_PROVIDER_OR_STORAGE_ERROR")
        if once:
            return 0
        if not job_id:
            time.sleep(idle)


if __name__ == "__main__":
    raise SystemExit(main())
