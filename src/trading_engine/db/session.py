import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        database_url = os.environ["DATABASE_URL"]
        _engine = create_engine(database_url, future=True)
    return _engine


@contextmanager
def get_session():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), future=True)
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
