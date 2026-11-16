import pytest

from erp_platform.cli import main


def test_db_ping_prints_postgres_version(capsys: pytest.CaptureFixture[str]) -> None:
    main(["db", "ping"])
    assert capsys.readouterr().out.startswith("PostgreSQL 17")


def test_db_ping_exits_1_when_postgres_unreachable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Port 1 is never a Postgres server, so the connection is refused.
    monkeypatch.setenv("POSTGRES_PORT", "1")
    with pytest.raises(SystemExit) as exc:
        main(["db", "ping"])
    assert exc.value.code == 1
    assert "command failed" in caplog.text
