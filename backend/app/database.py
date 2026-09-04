from backend.app.config import settings

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker

    # Engine configured for MySQL with PyMySQL driver
    # pool_pre_ping checks connection health before issuing queries
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=(settings.APP_ENV == "development"),
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

    def get_db():
        """Dependency generator that provides a database session and ensures cleanup."""
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

except ImportError:
    # Graceful fallback when sqlalchemy is not yet installed in the current environment
    engine = None
    SessionLocal = None
    Base = object

    def get_db():
        raise RuntimeError("SQLAlchemy is required. Install requirements via pip install -r backend/requirements.txt")
