import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.shipments.common import DomainError


def normalize_instant(value: str, timezone: str | None = None) -> datetime:
    """Canonical ISO date or datetime; no epoch/time-only blanket inference."""
    value = value.strip()
    try:
        zone = ZoneInfo(timezone) if timezone else UTC
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.combine(date.fromisoformat(value), time(17), UTC)
        if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC)
        candidates = {
            parsed.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            for fold in (0, 1)
            if parsed.replace(tzinfo=zone, fold=fold)
            .astimezone(UTC)
            .astimezone(zone)
            .replace(tzinfo=None)
            == parsed
        }
        if len(candidates) != 1:
            raise ValueError
        return candidates.pop()
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        raise DomainError(
            400, "Invalid deadline or recipient timezone", "invalid_deadline"
        ) from None


def default_deadline(processed_at: datetime) -> datetime:
    day = processed_at.astimezone(UTC).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, time(17), UTC)


def display_instant(value: datetime, timezone: str | None) -> datetime:
    try:
        return value.astimezone(ZoneInfo(timezone) if timezone else UTC)
    except (ValueError, ZoneInfoNotFoundError):
        raise DomainError(
            400, "Invalid recipient timezone", "invalid_timezone"
        ) from None
