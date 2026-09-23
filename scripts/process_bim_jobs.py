from __future__ import annotations

import os
import socket
import time

from glip.config import settings
from glip.database import SessionLocal
from glip.bim.ifc_semantics import BIMSemanticError, IfcOpenShellSemanticEngine
from glip.bim.service import claim_next_bim_job, process_bim_extraction_job


def main() -> int:
    if not settings.bim_semantic_enabled:
        raise SystemExit("GLIP_BIM_SEMANTIC_ENABLED must be true")
    engine = IfcOpenShellSemanticEngine()
    if not engine.available():
        raise SystemExit("IfcOpenShell engine is not installed in this worker image")

    worker_id = settings.replica_id or f"{socket.gethostname()}:{os.getpid()}"
    idle_seconds = float(os.getenv("GLIP_BIM_WORKER_IDLE_SECONDS","2"))
    once = os.getenv("GLIP_BIM_WORKER_ONCE","false").lower() == "true"

    while True:
        with SessionLocal() as db:
            job = claim_next_bim_job(db, settings=settings, worker_id=worker_id)
            if not job:
                db.commit()
                if once:
                    return 0
            else:
                db.commit()
                try:
                    # A fresh transaction/session boundary avoids holding a row
                    # lock while parsing a potentially large IFC file.
                    job_id = job.id
                    with SessionLocal() as work_db:
                        from glip.models import BIMExtractionJob
                        from glip.bim.service import utcnow
                        current = work_db.get(BIMExtractionJob, job_id)
                        if current is None:
                            raise BIMSemanticError("BIM_JOB_NOT_FOUND")
                        try:
                            process_bim_extraction_job(
                                work_db, settings=settings, job=current, engine=engine
                            )
                        except Exception as exc:
                            # Always commit a terminal failure before releasing the
                            # lease so a bad IFC cannot loop forever.
                            if current.status != "failed":
                                current.status = "failed"
                                current.error_code = (
                                    str(exc) if isinstance(exc, BIMSemanticError)
                                    else "BIM_SEMANTIC_INTERNAL_ERROR"
                                )
                                current.completed_at = utcnow()
                                current.lease_owner = None
                                current.lease_expires_at = None
                            work_db.commit()
                            raise
                        else:
                            work_db.commit()
                except Exception:
                    # Failure state is already persisted above. Worker continues
                    # with the next job instead of crashing the queue.
                    pass
        if once:
            return 0
        time.sleep(idle_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
