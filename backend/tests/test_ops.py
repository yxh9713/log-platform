from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.ops import cli


def test_diagnostic_outage_is_sanitized(capsys: pytest.CaptureFixture[str]) -> None:
    engine = MagicMock()
    with (
        patch.object(cli, "create_database_engine", return_value=engine),
        patch.object(
            cli, "diagnose", side_effect=SQLAlchemyError("PRIVATE CONNECTION STRING")
        ),
    ):
        assert cli.main() == 1
    engine.dispose.assert_called_once()
    assert "PRIVATE" not in capsys.readouterr().out
