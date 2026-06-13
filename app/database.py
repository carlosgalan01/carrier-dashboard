import os
from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from app.models import Base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/calls.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_dashboard_schema()


def _ensure_dashboard_schema():
    inspector = inspect(engine)
    if "call_records" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("call_records")}
    dashboard_columns = {
        "loadboard_rate": "VARCHAR",
    }

    with engine.begin() as connection:
        for column_name, column_type in dashboard_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE call_records ADD COLUMN {column_name} {column_type}"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
