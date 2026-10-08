import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.loader import Row, insert_documents, rebuild_index
from app.main import create_app
from app.storage import SCHEMA


@pytest.fixture
def settings() -> Settings:
    # Separate database and index, so tests never touch the real data.
    return Settings(postgres_db="documents_test", elasticsearch_index="documents_test")


async def create_database_if_missing(settings: Settings) -> None:
    conn = await asyncpg.connect(**{**settings.postgres, "database": "postgres"})
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", settings.postgres_db):
            await conn.execute(f'CREATE DATABASE "{settings.postgres_db}"')
    finally:
        await conn.close()


@pytest.fixture
async def app(settings):
    """The app with a running lifespan and an empty test table and index."""
    await create_database_if_missing(settings)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        storage = app.state.storage
        async with storage.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS documents")
            await conn.execute(SCHEMA)
            await rebuild_index(conn, storage.es, storage.index)
        yield app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def seed(app):
    """Puts documents into the test DB and index; ids are assigned in order, starting from 1."""

    async def seed(rows: list[Row]) -> None:
        storage = app.state.storage
        async with storage.pool.acquire() as conn:
            await insert_documents(conn, rows)
            await rebuild_index(conn, storage.es, storage.index)

    return seed
