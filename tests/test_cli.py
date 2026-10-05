"""Command line: main.py only sends on demand; the web app owns the schedule."""

import pytest

import main


def test_send_now_runs_one_digest(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_runtime_config", lambda: {"k": 1})
    monkeypatch.setattr(main, "run_digest", lambda cfg: calls.append(cfg) or (True, "ok"))
    monkeypatch.setattr("sys.argv", ["main.py", "--send-now"])
    main.main()
    assert calls == [{"k": 1}]


def test_without_send_now_it_exits_and_points_to_the_web_app(monkeypatch, capsys):
    monkeypatch.setattr(main, "run_digest", lambda cfg: pytest.fail("must not send"))
    monkeypatch.setattr("sys.argv", ["main.py"])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2
    assert "uvicorn app:app" in capsys.readouterr().err
