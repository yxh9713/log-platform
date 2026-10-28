from typing import TYPE_CHECKING

from sqlalchemy import Connection

if TYPE_CHECKING:
    from app.carriers.service import EventResult


def load(
    connection: Connection, carrier: int, values: dict[str, str], receipt: int
) -> "EventResult":
    from app.carriers.service import process_event

    return process_event(connection, carrier, values, receipt, csv=True)
