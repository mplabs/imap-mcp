"""Tests for the audit log."""

import json

import pytest

from imap_mcp.audit import AuditLog


@pytest.fixture
def audit(tmp_path):
    log_path = tmp_path / "audit.log"
    return AuditLog(str(log_path))


class TestAuditLog:
    def test_write_creates_file(self, audit, tmp_path):
        audit.log("personal", "set_flags", {"id": "ref1", "add": ["\\Seen"]}, "ok")
        log_file = tmp_path / "audit.log"
        assert log_file.exists()

    def test_entry_is_valid_jsonl(self, audit, tmp_path):
        audit.log("personal", "move_email", {"id": "ref1", "to_folder": "Archive"}, "ok")
        log_file = tmp_path / "audit.log"
        line = log_file.read_text().strip()
        entry = json.loads(line)
        assert entry["account"] == "personal"
        assert entry["tool"] == "move_email"
        assert entry["result"] == "ok"
        assert "timestamp" in entry

    def test_secrets_redacted(self, audit, tmp_path):
        audit.log(
            "personal",
            "send_email",
            {"to": ["bob@example.com"], "password": "hunter2", "auth_token": "xyz"},
            "ok",
        )
        log_file = tmp_path / "audit.log"
        line = log_file.read_text().strip()
        assert "hunter2" not in line
        assert "xyz" not in line

    def test_multiple_entries_append(self, audit, tmp_path):
        audit.log("personal", "move_email", {}, "ok")
        audit.log("personal", "delete_email", {}, "ok")
        log_file = tmp_path / "audit.log"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_default_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        log = AuditLog()  # uses default path
        log.log("personal", "list_folders", {}, "ok")
        default = tmp_path / ".local" / "state" / "imap-mcp" / "audit.log"
        assert default.exists()
