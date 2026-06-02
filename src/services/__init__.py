"""Services: orchestration of collection, transformation and persistence."""

from .ingestion_service import IngestionResult, IngestionService

__all__ = ["IngestionService", "IngestionResult"]
