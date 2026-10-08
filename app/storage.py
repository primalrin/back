"""Postgres is the source of truth; Elasticsearch holds only the search index (id + text)."""

import asyncpg
from elasticsearch import AsyncElasticsearch

SEARCH_LIMIT = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rubrics      text[]    NOT NULL,
    text         text      NOT NULL,
    created_date timestamp NOT NULL
)
"""

INDEX_SETTINGS = {"number_of_shards": 1, "number_of_replicas": 0}
INDEX_MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        "id": {"type": "long"},
        "text": {"type": "text", "analyzer": "russian"},
    },
}


class Storage:
    def __init__(self, pool: asyncpg.Pool, es: AsyncElasticsearch, index: str) -> None:
        self.pool = pool
        self.es = es
        self.index = index

    async def search(self, query: str) -> list[asyncpg.Record]:
        """Top SEARCH_LIMIT documents by relevance, ordered by creation date (newest first)."""
        resp = await self.es.search(
            index=self.index, query={"match": {"text": query}}, size=SEARCH_LIMIT, source=["id"]
        )
        ids = [hit["_source"]["id"] for hit in resp["hits"]["hits"]]
        return await self.pool.fetch(
            """
            SELECT id, rubrics, text, created_date FROM documents
            WHERE id = ANY($1::bigint[])
            ORDER BY created_date DESC, id DESC
            """,
            ids,
        )

    async def delete(self, doc_id: int) -> bool:
        """Delete from Postgres and Elasticsearch. Returns False if there is no such document."""
        async with self.pool.acquire() as conn, conn.transaction():
            if await conn.fetchval("DELETE FROM documents WHERE id = $1 RETURNING id", doc_id) is None:
                return False
            # Still inside the transaction: if Elasticsearch fails, the row is rolled back,
            # so the document stays both in the DB and in the index.
            await self.es.options(ignore_status=404).delete(index=self.index, id=str(doc_id), refresh=True)
        return True
