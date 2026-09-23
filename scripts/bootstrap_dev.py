import argparse
from sqlalchemy import select
from glip.database import SessionLocal
from glip.models import Tenant,Membership
p=argparse.ArgumentParser();p.add_argument("--tenant-id",default="tenant-demo");p.add_argument("--subject",default="user-demo");p.add_argument("--apply",action="store_true")
a=p.parse_args();print({"tenant_id":a.tenant_id,"subject":a.subject,"write_executed":a.apply})
if a.apply:
    with SessionLocal() as db:
        if not db.scalar(select(Tenant).where(Tenant.id==a.tenant_id)): db.add(Tenant(id=a.tenant_id,name="GLIP Demo"))
        if not db.scalar(select(Membership).where(Membership.tenant_id==a.tenant_id,Membership.external_subject==a.subject)):
            db.add(Membership(tenant_id=a.tenant_id,external_subject=a.subject,display_name="Sabrina",role="owner",active=True))
        db.commit()
