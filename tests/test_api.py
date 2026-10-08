import json
from datetime import datetime
from pathlib import Path

import pytest

from app.loader import load
from app.main import create_app


def doc(text: str, created_date: str, rubrics: tuple[str, ...] = ("VK-1",)):
    return list(rubrics), text, datetime.fromisoformat(created_date)


async def search(client, query: str) -> list[dict]:
    resp = await client.get("/documents/search", params={"query": query})
    assert resp.status_code == 200
    return resp.json()


async def test_search_returns_db_documents_ordered_by_date(client, seed):
    await seed([
        doc("Котики захватили интернет", "2019-03-01 10:00:00", ("VK-1", "VK-2")),
        doc("Новости про собак", "2019-04-01 10:00:00"),
        doc("Ещё немного про котиков", "2019-05-01 10:00:00"),
        doc("Котик спит", "2019-01-01 10:00:00"),
    ])

    # Different word forms match thanks to the russian analyzer; the dog post doesn't match.
    assert await search(client, "котики") == [
        {"id": 3, "rubrics": ["VK-1"], "text": "Ещё немного про котиков", "created_date": "2019-05-01T10:00:00"},
        {"id": 1, "rubrics": ["VK-1", "VK-2"], "text": "Котики захватили интернет", "created_date": "2019-03-01T10:00:00"},
        {"id": 4, "rubrics": ["VK-1"], "text": "Котик спит", "created_date": "2019-01-01T10:00:00"},
    ]


async def test_search_returns_at_most_20_documents(client, seed):
    await seed([doc(f"Конкурс номер {i}", f"2019-01-{i:02d} 12:00:00") for i in range(1, 26)])

    found = await search(client, "конкурс")

    assert len(found) == 20
    dates = [d["created_date"] for d in found]
    assert dates == sorted(dates, reverse=True)


async def test_search_without_matches_returns_empty_list(client, seed):
    await seed([doc("Котики захватили интернет", "2019-03-01 10:00:00")])

    assert await search(client, "квантовая хромодинамика") == []


@pytest.mark.parametrize("params", [{}, {"query": ""}, {"query": "x" * 1001}])
async def test_search_validates_query(client, params):
    resp = await client.get("/documents/search", params=params)

    assert resp.status_code == 422


async def test_delete_removes_document_from_db_and_index(app, client, seed):
    await seed([doc("Котик раз", "2019-01-01 00:00:00"), doc("Котик два", "2019-01-02 00:00:00")])
    storage = app.state.storage

    resp = await client.delete("/documents/1")

    assert resp.status_code == 204
    assert await storage.pool.fetchval("SELECT count(*) FROM documents WHERE id = 1") == 0
    assert not await storage.es.exists(index=storage.index, id="1")
    assert [d["id"] for d in await search(client, "котик")] == [2]
    assert (await client.delete("/documents/1")).status_code == 404


async def test_delete_unknown_document_returns_404(client):
    resp = await client.delete("/documents/42")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Document not found"}


@pytest.mark.parametrize("doc_id", ["abc", "0", str(2**63)])
async def test_delete_validates_id(client, doc_id):
    resp = await client.delete(f"/documents/{doc_id}")

    assert resp.status_code == 422


async def test_delete_keeps_document_when_index_is_unavailable(app, client, seed, monkeypatch):
    await seed([doc("Котик", "2019-01-01 00:00:00")])
    storage = app.state.storage

    class BrokenElasticsearch:
        def options(self, **kwargs):
            return self

        async def delete(self, **kwargs):
            raise ConnectionError("Elasticsearch is unavailable")

    monkeypatch.setattr(storage, "es", BrokenElasticsearch())
    with pytest.raises(ConnectionError):
        await client.delete("/documents/1")

    assert await storage.pool.fetchval("SELECT count(*) FROM documents") == 1


async def test_loader_imports_dataset_once(app, client, settings):
    await load(settings)
    await load(settings)  # a restart must not duplicate the data
    storage = app.state.storage

    assert await storage.pool.fetchval("SELECT count(*) FROM documents") == 1500
    assert (await storage.es.count(index=storage.index))["count"] == 1500
    found = await search(client, "конкурс")
    assert len(found) == 20
    assert set(found[0]) == {"id", "rubrics", "text", "created_date"}
    dates = [d["created_date"] for d in found]
    assert dates == sorted(dates, reverse=True)


def test_docs_json_is_up_to_date():
    docs = json.loads((Path(__file__).parents[1] / "docs.json").read_text(encoding="utf-8"))

    assert docs == create_app().openapi(), "regenerate: python -m app.export_docs > docs.json"
