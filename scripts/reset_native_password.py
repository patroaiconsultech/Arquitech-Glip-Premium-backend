#!/usr/bin/env python3
from __future__ import annotations
import getpass, os
from datetime import datetime, timezone
from sqlalchemy import select
from glip.database import SessionLocal
from glip.models import NativeCredential
from glip.native_auth import new_password_record, normalize_email, revoke_all_credential_sessions

if os.getenv("GLIP_RESET_CONFIRM")!="YES":
    raise SystemExit("refusing: set GLIP_RESET_CONFIRM=YES")

tenant_id=os.environ.get("GLIP_RESET_TENANT_ID","").strip()
email=normalize_email(os.environ.get("GLIP_RESET_EMAIL",""))
password=os.environ.get("GLIP_RESET_PASSWORD") or getpass.getpass("New GLIP native password: ")
if not tenant_id or not email:
    raise SystemExit("tenant id and email are required")

salt_b64,hash_b64=new_password_record(password)
with SessionLocal() as db:
    credential=db.scalar(select(NativeCredential).where(
        NativeCredential.tenant_id==tenant_id,
        NativeCredential.email_normalized==email,
    ))
    if credential is None:
        raise SystemExit("native credential not found")
    credential.password_salt_b64=salt_b64
    credential.password_hash_b64=hash_b64
    credential.password_changed_at=datetime.now(timezone.utc)
    credential.failed_attempts=0
    db.flush()
    revoked=revoke_all_credential_sessions(db,credential_id=credential.id)
    db.commit()
print(f"native_password_reset_ok revoked_sessions={revoked}")
