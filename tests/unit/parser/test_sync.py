"""Unit tests for src.sync data synchronization orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.sync import (
    check_port_open,
    ensure_neo4j_running,
    get_neo4j_host_port,
    run_stage_neo4j,
    run_stage_parser,
    run_stage_rag,
    sync,
)


def test_get_neo4j_host_port_defaults() -> None:
    with patch.dict("os.environ", {"NEO4J_URI": "bolt://127.0.0.1:8888"}):
        host, port = get_neo4j_host_port()
        assert host == "127.0.0.1"
        assert port == 8888


def test_check_port_open_success() -> None:
    with patch("socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        assert check_port_open("localhost", 7687) is True


def test_check_port_open_failure() -> None:
    with patch("socket.create_connection", side_effect=OSError("Connection refused")):
        assert check_port_open("localhost", 7687) is False


def test_ensure_neo4j_running_already_open() -> None:
    with patch("src.sync.check_port_open", return_value=True):
        assert ensure_neo4j_running() is True


def test_ensure_neo4j_running_skip_docker() -> None:
    with patch("src.sync.check_port_open", return_value=False):
        assert ensure_neo4j_running(skip_docker=True) is False


def test_ensure_neo4j_running_no_docker_cli() -> None:
    with (
        patch("src.sync.check_port_open", return_value=False),
        patch("shutil.which", return_value=None),
    ):
        assert ensure_neo4j_running() is False


def test_ensure_neo4j_running_with_docker_success() -> None:
    with (
        patch("src.sync.check_port_open", side_effect=[False, False, True]),
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run") as mock_run,
        patch("time.sleep", return_value=None),
    ):
        mock_run.return_value.returncode = 0
        assert ensure_neo4j_running(max_wait_sec=5) is True
        mock_run.assert_called_once_with(["docker", "compose", "up", "-d"], check=True)


def test_run_stage_parser_success() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        ok, elapsed, status = run_stage_parser()
        assert ok is True
        assert status == "SUCCESS"
        assert elapsed >= 0.0


def test_run_stage_neo4j_dry_run() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        ok, _, status = run_stage_neo4j(doc_id=None, dry_run=True)
        assert ok is True
        assert status == "SUCCESS"
        assert "--dry-run" in mock_run.call_args[0][0]


def test_run_stage_rag_doc() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        ok, _, status = run_stage_rag(doc_id="168_2024_ND-CP", dry_run=False)
        assert ok is True
        assert status == "SUCCESS"
        cmd = mock_run.call_args[0][0]
        assert "--doc" in cmd
        assert "168_2024_ND-CP" in cmd


def test_sync_dry_run_workflow() -> None:
    with (
        patch("src.sync.run_stage_parser", return_value=(True, 0.1, "SUCCESS")),
        patch("src.sync.run_stage_neo4j", return_value=(True, 0.2, "SUCCESS")),
        patch("src.sync.run_stage_rag", return_value=(True, 0.3, "SUCCESS")),
    ):
        code = sync(dry_run=True)
        assert code == 0


def test_sync_aborts_on_parser_failure() -> None:
    with patch(
        "src.sync.run_stage_parser", return_value=(False, 0.1, "FAILED (code 1)")
    ):
        code = sync(dry_run=True)
        assert code == 1


def test_sync_aborts_on_neo4j_unavailable() -> None:
    with patch("src.sync.ensure_neo4j_running", return_value=False):
        code = sync(dry_run=False)
        assert code == 1
