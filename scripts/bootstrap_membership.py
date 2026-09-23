#!/usr/bin/env python3
from __future__ import annotations
import getpass, os
from uuid import uuid4
from sqlalchemy import select
from glip.database import SessionLocal
from glip.models import Membership, NativeCredential, Tenant
from glip.native_auth import new_password_record, normalize_email, valid_email_shape

if os.getenv("GLIP_BOOTSTRAP_CONFIRM")!="YES":
    raise SystemExit("refusing: set GLIP_BOOTSTRAP_CONFIRM=YES")

tenant_id=os.environ.get("GLIP_BOOTSTRAP_TENANT_ID","").strip()
tenant_name=os.environ.get("GLIP_BOOTSTRAP_TENANT_NAME","").strip()
email=normalize_email(os.environ.get("GLIP_BOOTSTRAP_EMAIL",""))
display_name=os.environ.get("GLIP_BOOTSTRAP_DISPLAY_NAME","").strip() or None
role=os.environ.get("GLIP_BOOTSTRAP_ROLE","owner").strip() or "owner"
password=os.environ.get("GLIP_BOOTSTRAP_PASSWORD") or getpass.getpass("GLIP native password: ")

if not tenant_id or not tenant_name or not valid_email_shape(email):
    raise SystemExit("tenant id, tenant name and a valid email are required")

salt_b64,hash_b64=new_password_record(password)
credential_id=str(uuid4())
membership_id=str(uuid4())

with SessionLocal() as db:
    existing=db.scalar(select(NativeCredential).where(
        NativeCredential.tenant_id==tenant_id,
        NativeCredential.email_normalized==email,
    ))
    if existing is not None:
        raise SystemExit("refusing: native credential already exists for tenant/email")

    tenant=db.get(Tenant,tenant_id)
    if tenant is None:
        db.add(Tenant(id=tenant_id,name=tenant_name))

    db.add_all([
        Membership(
            id=membership_id,
            tenant_id=tenant_id,
            external_subject=f"native:{credential_id}",
            display_name=display_name,
            role=role,
            active=True,
        ),
        NativeCredential(
            id=credential_id,
            tenant_id=tenant_id,
            membership_id=membership_id,
            email_normalized=email,
            password_salt_b64=salt_b64,
            password_hash_b64=hash_b64,
            active=True,
        ),
    ])
    db.commit()

print("native_bootstrap_ok")
