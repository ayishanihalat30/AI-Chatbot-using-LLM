import asyncio

from app.services.ingest import process_document


def run_process_document(doc_id: str) -> None:
    """RQ entrypoint (sync). Runs the async ingestion pipeline to completion."""
    asyncio.run(process_document(doc_id))
