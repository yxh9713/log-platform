from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ExportAccepted(BaseModel):
    message: Literal["we start to process data"] = "we start to process data"


class ExportStatus(BaseModel):
    id: UUID
    state: Literal["pending", "retry_wait", "ready", "failed"]
    created_at: datetime
    url: str | None
    row_count: int | None
    reason_code: str | None


class ExportList(BaseModel):
    items: list[ExportStatus]
