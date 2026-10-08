"""Imports posts.csv into Postgres and builds the Elasticsearch index from Postgres.

Safe to run on every start: the CSV is imported only into an empty table, and the index
is rebuilt only when it is missing or out of sync with the table.

    python -m app.loader
"""

import ast
import asyncio
import csv
import logging
from datetime import datetime

import asyncpg
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from app.config import Settings
from app.storage import INDEX_MAPPINGS, INDEX_SETTINGS, SCHEMA

log = logging.getLogger("loader")

Row = tuple[list[str], str, datetime]  # rubrics, text, created_date


def read_csv(path: str) -> list[Row]:
    with open(path, encoding="utf-8", newline="") as f:
        return [
            # rubrics are stored as a Python list literal: "['VK-1603736028819866', ...]"
            (ast.literal_eval(row["rubrics"]), row["text"], datetime.fromisoformat(row["created_date"]))
            for row in csv.DictReader(f)
        ]


async def insert_documents(conn: asyncpg.Connection, rows: list[Row]) -> None:
    await conn.copy_records_to_table("documents", records=rows, columns=["rubrics", "text", "created_date"])


async def rebuild_index(conn: asyncpg.Connection, es: AsyncElasticsearch, index: str) -> int:
    await es.options(ignore_status=404).indices.delete(index=index)
    await es.indices.create(index=index, settings=INDEX_SETTINGS, mappings=INDEX_MAPPINGS)
    rows = await conn.fetch("SELECT id, text FROM documents")
    actions = ({"_index": index, "_id": str(r["id"]), "_source": {"id": r["id"], "text": r["text"]}} for r in rows)
    indexed, _ = await async_bulk(es, actions, refresh=True)
    return indexed


async def load(settings: Settings) -> None:
    conn = await asyncpg.connect(**settings.postgres)
    try:
        async with AsyncElasticsearch(settings.elasticsearch_url) as es:
            await conn.execute(SCHEMA)
            count = await conn.fetchval("SELECT count(*) FROM documents")
            if count == 0:
                rows = read_csv(settings.csv_path)
                await insert_documents(conn, rows)
                count = len(rows)
                log.info("Imported %d documents from %s", count, settings.csv_path)

            resp = await es.options(ignore_status=404).count(index=settings.elasticsearch_index)
            if resp.body.get("count") != count:
                indexed = await rebuild_index(conn, es, settings.elasticsearch_index)
                log.info("Indexed %d documents into '%s'", indexed, settings.elasticsearch_index)
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    asyncio.run(load(Settings()))
