from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker,Session
from app.core.config import settings


# SQLAlchemy Base Class
class Base(DeclarativeBase):
    pass

# Database Engine

engine = create_engine(

    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
)

# Database Session

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
)

# Database Dependency

def get_db():
    db: Session = SessionLocal()

    try:
        yield db

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()