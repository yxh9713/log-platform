import sqlalchemy as sa
from sqlalchemy import Connection, Engine
from sqlalchemy.dialects.postgresql import insert

from app.db.schema import company
from app.shipments.common import DomainError, lock_tenant
from app.shipments.schema import account_mapping, carrier_accounts


def company_type(connection: Connection, company_id: int, expected: int) -> None:
    if not connection.execute(
        sa.select(company.c.id).where(
            company.c.id == company_id,
            company.c.company_type == expected,
            company.c.active.is_(True),
        )
    ).first():
        raise DomainError(
            400, "Invalid active company assignment", "invalid_assignment"
        )


class AccountMappingService:
    """Trusted operator/source configuration; intentionally no portal endpoint."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def configure(
        self, shipper_id: int, carrier_id: int, service: str, account: str
    ) -> None:
        service, account = service.strip(), account.strip()
        if not service or len(service) > 64 or not account or len(account) > 255:
            raise DomainError(400, "Invalid service or account", "invalid_assignment")
        with self.engine.begin() as connection:
            lock_tenant(connection, shipper_id)
            company_type(connection, shipper_id, 2)
            company_type(connection, carrier_id, 1)
            connection.execute(
                insert(carrier_accounts)
                .values(
                    carrier_company_id=carrier_id,
                    shipper_company_id=shipper_id,
                    account_id=account,
                )
                .on_conflict_do_nothing(constraint="uq_carrier_accounts_pair")
            )
            owner = connection.execute(
                sa.select(carrier_accounts.c.shipper_company_id).where(
                    carrier_accounts.c.carrier_company_id == carrier_id,
                    carrier_accounts.c.account_id == account,
                )
            ).scalar_one()
            if owner != shipper_id:
                raise DomainError(
                    400, "Carrier account is already assigned", "account_conflict"
                )
            connection.execute(
                insert(account_mapping)
                .values(
                    shipper_company_id=shipper_id,
                    carrier_company_id=carrier_id,
                    service=service,
                    account_id=account,
                )
                .on_conflict_do_update(
                    constraint="uq_account_mapping_shipper_service",
                    set_={
                        "carrier_company_id": carrier_id,
                        "account_id": account,
                        "updated_at": sa.func.now(),
                    },
                )
            )

    @staticmethod
    def resolve_shipper(connection: Connection, carrier_id: int, account: str) -> int:
        company_type(connection, carrier_id, 1)
        owner = connection.execute(
            sa.select(carrier_accounts.c.shipper_company_id).where(
                carrier_accounts.c.carrier_company_id == carrier_id,
                carrier_accounts.c.account_id == account,
            )
        ).scalar_one_or_none()
        if owner is None:
            raise DomainError(
                400, "Unknown carrier account assignment", "unknown_account"
            )
        company_type(connection, int(owner), 2)
        return int(owner)


def creation_assignment(
    connection: Connection, shipper_id: int, service: str, account: str
) -> int:
    row = connection.execute(
        sa.select(
            account_mapping.c.carrier_company_id, account_mapping.c.account_id
        ).where(
            account_mapping.c.shipper_company_id == shipper_id,
            account_mapping.c.service == service,
        )
    ).one_or_none()
    if row is None or row.account_id != account:
        raise DomainError(
            400, "Invalid service or account assignment", "invalid_assignment"
        )
    company_type(connection, int(row.carrier_company_id), 1)
    return int(row.carrier_company_id)
