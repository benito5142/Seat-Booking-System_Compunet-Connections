from backend.app.config import settings

try:
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import declarative_base, sessionmaker

    db_url = settings.DATABASE_URL
    connect_args = {}
    is_sqlite = "sqlite" in db_url

    if is_sqlite:
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 30.0

    # Engine configured for MySQL with PyMySQL driver or SQLite
    engine = create_engine(
        db_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=3600 if not is_sqlite else -1,
        echo=(settings.APP_ENV == "development"),
    )

    if is_sqlite:
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute("PRAGMA busy_timeout = 30000;")
            cursor.close()

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
