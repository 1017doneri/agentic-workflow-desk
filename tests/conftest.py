import os
import uuid
import pytest
import httpx
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app import api as api_module
from app.api import app


TEST_DB_URL=os.getenv("TEST_DB_URL","postgresql://postgres:postgres@127.0.0.1:5432/langgraph")



@pytest.fixture
async def db_pool():
    pool=AsyncConnectionPool(
        conninfo=TEST_DB_URL,
        open=False,
        kwargs={"autocommit":True,"row_factory":dict_row}
    )
    await pool.open(wait=True)
    async with pool.connection() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        hashed_password TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
        )
        """)
    yield pool
    await pool.close()

@pytest.fixture
async def client(db_pool,monkeypatch):
    monkeypatch.setattr(api_module,"user_pool",db_pool)
    transport=httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,base_url="http://test")as c:
       yield c

@pytest.fixture
def unique_user():
    return f"test_{uuid.uuid4().hex[:8]}"