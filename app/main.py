from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

import asyncpg
from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request, status
from pydantic import BaseModel

from app.config import Settings
from app.storage import Storage


class Document(BaseModel):
    id: int
    rubrics: list[str]
    text: str
    created_date: datetime


class Error(BaseModel):
    detail: str


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


StorageDep = Annotated[Storage, Depends(get_storage)]
SearchQuery = Annotated[str, Query(min_length=1, max_length=1000, description="Произвольный текстовый запрос")]
DocumentId = Annotated[int, Path(ge=1, le=2**63 - 1, description="id документа")]  # bigint range

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/search", summary="Поиск документов")
async def search_documents(storage: StorageDep, query: SearchQuery) -> list[Document]:
    """Ищет по тексту документов в индексе Elasticsearch (с учётом морфологии русского языка).

    Возвращает первые 20 самых релевантных документов со всеми полями из БД,
    упорядоченные по дате создания: сначала новые.
    """
    return [Document(**row) for row in await storage.search(query)]


@router.delete(
    "/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление документа",
    responses={status.HTTP_404_NOT_FOUND: {"model": Error, "description": "Документ не найден"}},
)
async def delete_document(storage: StorageDep, doc_id: DocumentId) -> None:
    """Удаляет документ из БД и из поискового индекса."""
    if not await storage.delete(doc_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with (
            asyncpg.create_pool(**settings.postgres) as pool,
            AsyncElasticsearch(settings.elasticsearch_url) as es,
        ):
            app.state.storage = Storage(pool, es, settings.elasticsearch_index)
            yield

    app = FastAPI(
        title="Document search",
        description="Простой поисковик по текстам документов: Postgres + Elasticsearch.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app
