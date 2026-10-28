import hashlib

import sqlalchemy as sa
from sqlalchemy import Connection

from app.auth.dto import Principal
from app.db.schema import company, user_role, users


class DomainError(Exception):
    def __init__(
        self, status: int, message: str, code: str = "invalid_request"
    ) -> None:
        self.status = status
        self.message = message
        self.code = code
        super().__init__(message)


def lock_tenant(connection: Connection, company_id: int) -> None:
    key = int.from_bytes(
        hashlib.sha256(f"p4:shipper:{company_id}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    connection.execute(sa.select(sa.func.pg_advisory_xact_lock(key)))


def shipper_scope(
    connection: Connection, principal: Principal, administrator: bool = False
) -> int:
    company_id = int(principal.company.id)
    role = connection.execute(
        sa.select(user_role.c.name)
        .select_from(users.join(company).join(user_role))
        .where(
            users.c.id == int(principal.id),
            users.c.company_id == company_id,
            users.c.active.is_(True),
            company.c.active.is_(True),
            company.c.company_type == 2,
            user_role.c.name.in_(["administrator", "user"]),
        )
        .with_for_update(read=True, of=[users.c.id, company.c.id, user_role.c.id])
    ).scalar_one_or_none()
    if role is None:
        raise DomainError(401, "Authentication required", "invalid_membership")
    if administrator and role != "administrator":
        raise DomainError(403, "Administrator role required", "role_required")
    return company_id
