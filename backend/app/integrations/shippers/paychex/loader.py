from datetime import datetime

from sqlalchemy import Connection

from app.ingestion.shipments import manifest_upsert
from app.integrations.shippers.paychex.transformer import transform


def load(
    connection: Connection,
    company_id: int,
    row: dict[str, str],
    processed_at: datetime,
    receipt: int,
) -> int:
    return manifest_upsert(
        connection, company_id, transform(row), processed_at, receipt
    )
