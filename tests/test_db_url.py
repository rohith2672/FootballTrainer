from sqlalchemy import create_engine

from src.db_url import sqlalchemy_url


def test_default_postgresql_url_uses_installed_driver_without_connecting():
    engine = create_engine(sqlalchemy_url("postgresql://user:password@localhost/test"))
    try:
        assert engine.dialect.driver == "psycopg2"
    finally:
        engine.dispose()


def test_explicit_driver_and_encoded_password_are_preserved():
    value = "postgresql+psycopg2://user:p%40ss%25@localhost/test"
    assert sqlalchemy_url(value) == value


def test_other_database_urls_are_unchanged():
    assert sqlalchemy_url("sqlite:///:memory:") == "sqlite:///:memory:"
