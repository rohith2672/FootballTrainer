"""Cached publisher headlines remain available independently of the model."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from src.database import DatabaseNotConfigured, get_db
from src.news.service import read_news

logger = logging.getLogger(__name__)
router = APIRouter()


class ArticleResponse(BaseModel):
    id: str
    title: str
    url: str
    publisher: str
    published_at: str | None
    fetched_at: str


class NewsResponse(BaseModel):
    articles: list[ArticleResponse]
    last_attempt_at: str | None
    last_success_at: str | None
    next_check_at: str | None
    status: Literal["ok", "stale", "unavailable"]
    stale: bool


def news_db():
    try:
        yield from get_db()
    except (DatabaseNotConfigured, SQLAlchemyError) as exc:
        logger.warning("News database unavailable", exc_info=True)
        raise HTTPException(503, "News storage unavailable") from exc


@router.get("/news", response_model=NewsResponse)
def get_news(limit: int = Query(50, ge=1, le=100), db=Depends(news_db)):
    try:
        return read_news(db, limit)
    except SQLAlchemyError as exc:
        logger.warning("News database unavailable", exc_info=True)
        raise HTTPException(503, "News storage unavailable") from exc
