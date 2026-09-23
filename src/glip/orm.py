from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """GLIP ORM metadata root.

    This module intentionally creates no engine and opens no connection.
    Alembic imports this metadata both online and offline.
    """
    pass
