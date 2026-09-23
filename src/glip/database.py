from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings
from .orm import Base

kwargs={"connect_args":{"check_same_thread":False}} if settings.database_url.startswith("sqlite") else {}
engine=create_engine(settings.database_url,pool_pre_ping=True,**kwargs)
SessionLocal=sessionmaker(bind=engine,expire_on_commit=False,autoflush=False)

def get_db():
    db=SessionLocal()
    try:
        yield db
    finally:
        db.close()
