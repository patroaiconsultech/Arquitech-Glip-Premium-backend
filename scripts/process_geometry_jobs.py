
from __future__ import annotations

import os
import socket
import time

from glip.config import settings
from glip.database import SessionLocal
from glip.geometry.glb_preview import GeometryPreviewError, TrimeshLinePreviewEngine
from glip.geometry.service import claim_next_geometry_job, process_geometry_build_job, utcnow
from glip.models import GeometryBuildJob


def main() -> int:
    if not settings.geometry_build_enabled:
        raise SystemExit("GLIP_GEOMETRY_BUILD_ENABLED must be true")
    engine=TrimeshLinePreviewEngine()
    if not engine.available():
        raise SystemExit("trimesh engine is not installed in this worker image")
    worker_id=settings.replica_id or f"{socket.gethostname()}:{os.getpid()}"
    idle=float(os.getenv("GLIP_GEOMETRY_WORKER_IDLE_SECONDS","2"))
    once=os.getenv("GLIP_GEOMETRY_WORKER_ONCE","false").lower()=="true"
    while True:
        with SessionLocal() as db:
            job=claim_next_geometry_job(db,settings=settings,worker_id=worker_id)
            if not job:
                db.commit()
                if once:return 0
            else:
                job_id=job.id;db.commit()
                with SessionLocal() as work_db:
                    current=work_db.get(GeometryBuildJob,job_id)
                    if current is None:
                        raise GeometryPreviewError("GEOMETRY_JOB_NOT_FOUND")
                    try:
                        process_geometry_build_job(work_db,settings=settings,job=current,engine=engine)
                    except Exception as exc:
                        if current.status!="failed":
                            current.status="failed"
                            current.error_code=str(exc) if isinstance(exc,GeometryPreviewError) else "GEOMETRY_INTERNAL_ERROR"
                            current.completed_at=utcnow()
                            current.lease_owner=None;current.lease_expires_at=None
                        work_db.commit()
                    else:
                        work_db.commit()
        if once:return 0
        time.sleep(idle)


if __name__=="__main__":
    raise SystemExit(main())
