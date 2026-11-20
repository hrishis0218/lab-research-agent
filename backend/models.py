"""Typed public API contracts. Paths and secrets are intentionally absent."""

from pydantic import BaseModel


class LibraryStats(BaseModel):
    on_disk: int
    indexed: int
    indexed_on_disk: int
    unindexed: int
    missing: int
    passages: int
    database_available: bool
    folder_available: bool
    duplicate_copies: int | None
    duplicate_status: str
    mode: str


class DocumentSummary(BaseModel):
    bibliography: dict | None = None
    processing_state: str | None = None
    attachments: list[dict] = []
    id: int
    title: str
    filename: str
    pages: int | None
    passages: int
    available: bool


class DocumentDetail(DocumentSummary):
    bibliography: dict | None = None
    page: int
    excerpt: str | None
    source_id: int | None
    abstract: str | None
    authors: str | None
    doi: str | None
    metadata_provenance: str


class Source(BaseModel):
    bibliography: dict | None = None
    source_id: int
    document_id: int
    title: str
    page: int
    excerpt: str
    citation: str


class SearchResult(BaseModel):
    sources: list[Source]
    mode: str
    notice: str
