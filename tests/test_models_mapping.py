from sqlalchemy import select
from sqlalchemy.orm import configure_mappers

from bot.db import models


def test_sqlalchemy_mappers_configure() -> None:
    configure_mappers()


def test_select_user_statement_builds() -> None:
    statement = select(models.User)
    assert "FROM users" in str(statement)
