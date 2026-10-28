import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from app.auth.dto import Principal
from app.shipments.common import DomainError, lock_tenant, shipper_scope
from app.shipments.dto import AreaInput, AreaOutput
from app.shipments.schema import area


class AreaService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, principal: Principal) -> list[AreaOutput]:
        with self.engine.begin() as connection:
            company_id = shipper_scope(connection, principal)
            return [
                AreaOutput(id=row.id, name=row.name)
                for row in connection.execute(
                    sa.select(area.c.id, area.c.name)
                    .where(area.c.company_id == company_id, area.c.deleted_at.is_(None))
                    .order_by(area.c.name)
                )
            ]

    def create(
        self, principal: Principal, payload: AreaInput
    ) -> tuple[AreaOutput, bool]:
        with self.engine.begin() as connection:
            lock_tenant(connection, int(principal.company.id))
            company_id = shipper_scope(connection, principal, administrator=True)
            inserted = connection.execute(
                insert(area)
                .values(company_id=company_id, name=payload.name)
                .on_conflict_do_nothing(constraint="uq_area_company_name")
                .returning(area.c.id)
            ).scalar_one_or_none()
            if inserted is not None:
                return AreaOutput(id=inserted, name=payload.name), True
            row = (
                connection.execute(
                    sa.select(area)
                    .where(area.c.company_id == company_id, area.c.name == payload.name)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if row["deleted_at"] is None:
                raise DomainError(
                    400, f"{payload.name} already exist", "duplicate_area"
                )
            connection.execute(
                area.update()
                .where(area.c.id == row["id"])
                .values(deleted_at=None, updated_at=sa.func.now())
            )
            return AreaOutput(id=row["id"], name=row["name"]), False

    def rename(
        self, principal: Principal, area_id: int, payload: AreaInput
    ) -> AreaOutput:
        with self.engine.begin() as connection:
            lock_tenant(connection, int(principal.company.id))
            company_id = shipper_scope(connection, principal, administrator=True)
            row = (
                connection.execute(
                    sa.select(area)
                    .where(area.c.id == area_id, area.c.company_id == company_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise DomainError(404, "Area not found", "area_not_found")
            if row["deleted_at"] is not None:
                raise DomainError(
                    400, "Restore the area before editing", "deleted_area"
                )
            conflict = connection.execute(
                sa.select(area.c.id).where(
                    area.c.company_id == company_id,
                    area.c.name == payload.name,
                    area.c.id != area_id,
                )
            ).first()
            if conflict:
                return AreaOutput(id=row["id"], name=row["name"])
            connection.execute(
                area.update()
                .where(area.c.id == area_id)
                .values(name=payload.name, updated_at=sa.func.now())
            )
            return AreaOutput(id=area_id, name=payload.name)

    def delete(self, principal: Principal, area_id: int) -> None:
        with self.engine.begin() as connection:
            lock_tenant(connection, int(principal.company.id))
            company_id = shipper_scope(connection, principal, administrator=True)
            row = connection.execute(
                sa.select(area.c.deleted_at)
                .where(area.c.id == area_id, area.c.company_id == company_id)
                .with_for_update()
            ).one_or_none()
            if row is None:
                raise DomainError(404, "Area not found", "area_not_found")
            if row.deleted_at is None:
                connection.execute(
                    area.update()
                    .where(area.c.id == area_id)
                    .values(deleted_at=sa.func.now(), updated_at=sa.func.now())
                )

    @staticmethod
    def validate_name(value: str) -> str:
        try:
            return AreaInput(name=value).name
        except ValidationError:
            raise DomainError(400, "Invalid area name", "invalid_area") from None
