import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import sqlalchemy as sa
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import Engine

from app.auth.dto import CompanyIdentity, LoginInput, Principal
from app.db.schema import auth_sessions, company, user_role, users
from app.passwords import hash_password, verify_password

SESSION_SECONDS = 8 * 60 * 60


class InvalidSession(Exception):
    pass


class InvalidLogin(Exception):
    pass


class LoginLimited(Exception):
    pass


@dataclass(frozen=True)
class LoginResult:
    token: str = field(repr=False)
    principal: Principal


class AuthService:
    def __init__(
        self, engine: Engine, secret: str, allow_login: Callable[[str, str], bool]
    ) -> None:
        self.engine = engine
        self.signer = URLSafeTimedSerializer(
            secret,
            salt="logistics-portal-session-v1",
            signer_kwargs={"digest_method": hashlib.sha256},
        )
        self.allow_login = allow_login
        # Missing identities still perform one real password verification.
        self.dummy_hash = hash_password(secrets.token_urlsafe(24))

    def login(self, payload: LoginInput, ip: str) -> LoginResult:
        if not self.allow_login(ip, f"{payload.slug}\0{payload.email}"):
            raise LoginLimited
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(
                        users.c.id,
                        users.c.company_id,
                        users.c.password,
                        users.c.active.label("user_active"),
                        company.c.active,
                        company.c.company_type,
                        user_role.c.name.label("role"),
                    )
                    .select_from(users.join(company).join(user_role))
                    .where(
                        users.c.email == payload.email, company.c.slug == payload.slug
                    )
                    .with_for_update(read=True, of=[users.c.id, company.c.id])
                )
                .mappings()
                .one_or_none()
            )
            valid_password = verify_password(
                payload.password.get_secret_value(),
                row["password"] if row is not None else self.dummy_hash,
            )
            if (
                row is None
                or not valid_password
                or not row["user_active"]
                or not row["active"]
                or row["company_type"] != 2
                or row["role"] not in ("administrator", "user")
            ):
                raise InvalidLogin
            session_id = secrets.token_urlsafe(32)
            now: datetime = connection.execute(sa.select(sa.func.now())).scalar_one()
            connection.execute(
                auth_sessions.insert().values(
                    token_hash=self.digest(session_id),
                    user_id=row["id"],
                    company_id=row["company_id"],
                    expires_at=now + timedelta(seconds=SESSION_SECONDS),
                )
            )
        token = str(self.signer.dumps(session_id))
        try:
            return LoginResult(token, self.authenticate(token))
        except InvalidSession:
            raise InvalidLogin from None

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def token_hash(self, token: str) -> str:
        if not token or len(token) > 2048:
            raise InvalidSession
        try:
            session_id = self.signer.loads(token, max_age=SESSION_SECONDS)
        except BadData:
            raise InvalidSession from None
        if not isinstance(session_id, str) or len(session_id) != 43:
            raise InvalidSession
        return self.digest(session_id)

    def authenticate(self, token: str) -> Principal:
        token_hash = self.token_hash(token)
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(
                        users.c.id,
                        users.c.email,
                        user_role.c.name.label("role"),
                        company.c.id.label("company_id"),
                        company.c.name,
                        company.c.slug,
                        auth_sessions.c.expires_at,
                    )
                    .select_from(
                        auth_sessions.join(users)
                        .join(company, users.c.company_id == company.c.id)
                        .join(user_role)
                    )
                    .where(
                        auth_sessions.c.token_hash == token_hash,
                        auth_sessions.c.company_id == users.c.company_id,
                        auth_sessions.c.expires_at > sa.func.now(),
                        users.c.active.is_(True),
                        company.c.active.is_(True),
                        company.c.company_type == 2,
                        user_role.c.name.in_(["administrator", "user"]),
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise InvalidSession
        return Principal(
            id=str(row["id"]),
            email=row["email"],
            role=row["role"],
            company=CompanyIdentity(
                id=str(row["company_id"]), name=row["name"], slug=row["slug"]
            ),
            expires_at=row["expires_at"],
        )

    def logout(self, token: str) -> None:
        token_hash = self.token_hash(token)
        with self.engine.begin() as connection:
            connection.execute(
                auth_sessions.delete().where(auth_sessions.c.token_hash == token_hash)
            )
