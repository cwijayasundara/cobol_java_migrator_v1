import os
import pytest
from sqlalchemy import create_engine, inspect

testcontainers = pytest.importorskip("testcontainers.postgres")
from testcontainers.postgres import PostgresContainer

EXPECTED = {"workspace", "journey_stage", "agent_run", "artifact",
            "gate", "approval", "budget"}

def test_alembic_upgrade_head_creates_all_tables():
    with PostgresContainer("postgres:16") as pg:
        url = pg.get_connection_url().replace("psycopg2", "psycopg")
        os.environ["POSTGRES_URL"] = url
        from alembic.config import Config
        from alembic import command
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        insp = inspect(create_engine(url))
        assert EXPECTED.issubset(set(insp.get_table_names()))
