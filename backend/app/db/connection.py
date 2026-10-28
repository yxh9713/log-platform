from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

from app.config import DatabaseSettings


def create_database_engine(settings: DatabaseSettings) -> Engine:
    url = make_url(str(settings.database_url)).set(drivername="postgresql+psycopg")
    return create_engine(
        url,
        connect_args={"options": "-c timezone=UTC", "connect_timeout": 5},
        hide_parameters=True,
    )
