"""Tests for config loading and secret resolution."""

import os
import textwrap
from unittest.mock import patch

import pytest

from imap_mcp.config import (
    ImapConfig, SmtpConfig, MailServerConfig,
    AuthConfig, load_config, resolve_secret,
)


MINIMAL_YAML = textwrap.dedent("""\
    default_account: personal

    accounts:
      personal:
        imap:
          host: imap.fastmail.com
          port: 993
          tls: true
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
        smtp:
          host: smtp.fastmail.com
          port: 465
          tls: true
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
        identity:
          from: "Me <me@example.com>"
""")

FULL_YAML = textwrap.dedent("""\
    default_account: personal

    accounts:
      personal:
        imap:
          host: imap.fastmail.com
          port: 993
          tls: true
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
        smtp:
          host: smtp.fastmail.com
          port: 465
          tls: true
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
        identity:
          from: "Me <me@example.com>"
          reply_to: "archive@example.com"
        folders:
          inbox: INBOX
          sent: Sent Items
          trash: Deleted
        safety:
          allow_delete: true
          confirm_batch_threshold: 10
        rate_limit:
          max_ops_per_minute: 30
        resolver:
          max_search_folders: 5
        attachment:
          max_size_mb: 25
        sieve:
          host: imap.fastmail.com
          port: 4190
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
      work:
        imap:
          host: imap.work.com
          port: 993
          tls: true
          username: me@work.com
          auth:
            method: password
            secret_ref: "env:IMAP_WORK_PASS"
        smtp:
          host: smtp.work.com
          port: 587
          tls: false
          starttls: true
          username: me@work.com
          auth:
            method: password
            secret_ref: "env:IMAP_WORK_PASS"
        identity:
          from: "Work Me <me@work.com>"
""")


@pytest.fixture
def config_file(tmp_path):
    def _write(content):
        p = tmp_path / "config.yaml"
        p.write_text(content)
        return str(p)
    return _write


class TestResolveSecret:
    def test_env_ref(self):
        with patch.dict(os.environ, {"MY_SECRET": "hunter2"}):
            assert resolve_secret("env:MY_SECRET") == "hunter2"

    def test_env_ref_missing(self):
        os.environ.pop("MISSING_VAR", None)
        with pytest.raises(ValueError, match="MISSING_VAR"):
            resolve_secret("env:MISSING_VAR")

    def test_keyring_ref(self):
        with patch("imap_mcp.config.keyring") as mock_kr:
            mock_kr.get_password.return_value = "s3cr3t"
            assert resolve_secret("keyring:service/user") == "s3cr3t"
            mock_kr.get_password.assert_called_once_with("service", "user")

    def test_keyring_ref_missing(self):
        with patch("imap_mcp.config.keyring") as mock_kr:
            mock_kr.get_password.return_value = None
            with pytest.raises(ValueError, match="keyring"):
                resolve_secret("keyring:service/user")

    def test_invalid_scheme(self):
        with pytest.raises(ValueError, match="Unsupported secret_ref"):
            resolve_secret("vault:some/path")

    def test_bare_string_passthrough(self):
        assert resolve_secret("plaintext") == "plaintext"


class TestMailServerConfigSharing:
    def test_imap_and_smtp_share_base(self):
        assert issubclass(ImapConfig, MailServerConfig)
        assert issubclass(SmtpConfig, MailServerConfig)

    def test_imap_config_fields(self):
        auth = AuthConfig(method="password", secret_ref="env:PASS")
        cfg = ImapConfig(host="h", port=993, tls=True, username="u", auth=auth)
        assert cfg.host == "h"
        assert cfg.starttls is False

    def test_smtp_starttls(self):
        auth = AuthConfig(method="password", secret_ref="env:PASS")
        cfg = SmtpConfig(host="h", port=587, tls=False, username="u", auth=auth, starttls=True)
        assert cfg.starttls is True


class TestLoadConfig:
    def test_minimal_config(self, config_file):
        path = config_file(MINIMAL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "secret"}):
            cfg = load_config(path)
        assert cfg.default_account == "personal"
        acc = cfg.accounts["personal"]
        assert acc.imap.host == "imap.fastmail.com"
        assert acc.smtp.host == "smtp.fastmail.com"
        assert acc.identity.from_addr == "Me <me@example.com>"

    def test_folder_defaults_applied(self, config_file):
        path = config_file(MINIMAL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x"}):
            cfg = load_config(path)
        f = cfg.accounts["personal"].folders
        assert f.inbox == "INBOX"
        assert f.sent == "Sent"
        assert f.drafts == "Drafts"
        assert f.trash == "Trash"
        assert f.spam == "Junk"

    def test_folder_overrides(self, config_file):
        path = config_file(FULL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x", "IMAP_WORK_PASS": "y"}):
            cfg = load_config(path)
        f = cfg.accounts["personal"].folders
        assert f.sent == "Sent Items"
        assert f.trash == "Deleted"
        assert f.inbox == "INBOX"  # not in YAML, uses default

    def test_safety_defaults(self, config_file):
        path = config_file(MINIMAL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x"}):
            cfg = load_config(path)
        s = cfg.accounts["personal"].safety
        assert s.allow_delete is False
        assert s.allow_empty_trash is False
        assert s.confirm_batch_threshold == 25

    def test_new_config_blocks(self, config_file):
        path = config_file(FULL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x", "IMAP_WORK_PASS": "y"}):
            cfg = load_config(path)
        acc = cfg.accounts["personal"]
        assert acc.rate_limit.max_ops_per_minute == 30
        assert acc.resolver.max_search_folders == 5
        assert acc.attachment.max_size_mb == 25
        assert acc.safety.allow_delete is True
        assert acc.safety.confirm_batch_threshold == 10

    def test_sieve_config_parsed(self, config_file):
        path = config_file(FULL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x", "IMAP_WORK_PASS": "y"}):
            cfg = load_config(path)
        sieve = cfg.accounts["personal"].sieve
        assert sieve is not None
        assert sieve.host == "imap.fastmail.com"
        assert sieve.port == 4190

    def test_sieve_absent_is_none(self, config_file):
        path = config_file(MINIMAL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x"}):
            cfg = load_config(path)
        assert cfg.accounts["personal"].sieve is None

    def test_multi_account(self, config_file):
        path = config_file(FULL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "p1", "IMAP_WORK_PASS": "p2"}):
            cfg = load_config(path)
        assert set(cfg.accounts.keys()) == {"personal", "work"}
        assert cfg.accounts["work"].smtp.starttls is True

    def test_missing_default_account(self, config_file):
        bad = MINIMAL_YAML.replace("default_account: personal", "default_account: ghost")
        path = config_file(bad)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x"}):
            with pytest.raises(ValueError, match="ghost"):
                load_config(path)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_config_env_var(self, config_file, monkeypatch):
        path = config_file(MINIMAL_YAML)
        monkeypatch.setenv("IMAP_MCP_CONFIG", path)
        monkeypatch.setenv("IMAP_PERSONAL_PASS", "secret")
        cfg = load_config()
        assert cfg.default_account == "personal"

    def test_server_defaults_when_absent(self, config_file):
        path = config_file(MINIMAL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x"}):
            cfg = load_config(path)
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 8000
        assert cfg.server.auth_token == ""
        assert cfg.server.request_timeout_s == 60

    def test_server_block_parsed(self, config_file, tmp_path):
        yaml_with_server = MINIMAL_YAML + textwrap.dedent("""\

            server:
              host: 127.0.0.1
              port: 9000
              auth_token: "env:IMAP_MCP_TOKEN"
              request_timeout_s: 30
        """)
        path = config_file(yaml_with_server)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x", "IMAP_MCP_TOKEN": "tok123"}):
            cfg = load_config(path)
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 9000
        assert cfg.server.auth_token == "tok123"   # secret resolved
        assert cfg.server.request_timeout_s == 30

    def test_server_auth_token_resolved_via_env(self, config_file):
        yaml_with_token = MINIMAL_YAML + "\nserver:\n  auth_token: \"env:MY_TOKEN\"\n"
        path = config_file(yaml_with_token)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x", "MY_TOKEN": "mysecret"}):
            cfg = load_config(path)
        assert cfg.server.auth_token == "mysecret"
