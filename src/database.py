import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


class Base(DeclarativeBase):
    pass


if DATABASE_URL:
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
else:
    engine = None
    SessionLocal = None


def get_db():
    if SessionLocal is None:
        raise EnvironmentError("DATABASE_URL is not set — copy .env.example to .env")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
