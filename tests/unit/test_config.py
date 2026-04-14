"""Tests for config loading and secret resolution."""

import os
import textwrap
from unittest.mock import patch, MagicMock

import pytest
import yaml

from imap_mcp.config import (
    Config,
    AccountConfig,
    ImapConfig,
    SmtpConfig,
    AuthConfig,
    IdentityConfig,
    FolderMappingConfig,
    SafetyConfig,
    load_config,
    resolve_secret,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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

MULTI_ACCOUNT_YAML = textwrap.dedent("""\
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
          from: "Me Work <me@work.com>"
          reply_to: "team@work.com"
""")


@pytest.fixture
def config_file(tmp_path):
    """Write a config YAML to a temp file and return its path."""
    def _write(content):
        p = tmp_path / "config.yaml"
        p.write_text(content)
        return str(p)
    return _write


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------

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
            result = resolve_secret("keyring:service/user")
            assert result == "s3cr3t"
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
        """A plain string (no scheme) is returned as-is for development."""
        # This lets developers hardcode a test password in config without
        # needing a keyring entry. The config module must support this.
        assert resolve_secret("plaintext") == "plaintext"


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

class TestAuthConfig:
    def test_password_method(self):
        a = AuthConfig(method="password", secret_ref="env:PASS")
        assert a.method == "password"
        assert a.secret_ref == "env:PASS"

    def test_xoauth2_method(self):
        a = AuthConfig(method="xoauth2", secret_ref="keyring:svc/usr")
        assert a.method == "xoauth2"

    def test_app_password_method(self):
        a = AuthConfig(method="app_password", secret_ref="env:PASS")
        assert a.method == "app_password"


class TestSafetyConfig:
    def test_defaults(self):
        s = SafetyConfig()
        assert s.allow_delete is False
        assert s.allow_empty_trash is False
        assert s.confirm_batch_threshold == 25


# ---------------------------------------------------------------------------
# Loading from YAML
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_minimal_config(self, config_file):
        path = config_file(MINIMAL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "secret"}):
            cfg = load_config(path)

        assert cfg.default_account == "personal"
        assert "personal" in cfg.accounts
        acc = cfg.accounts["personal"]
        assert isinstance(acc, AccountConfig)
        assert acc.imap.host == "imap.fastmail.com"
        assert acc.imap.port == 993
        assert acc.imap.tls is True
        assert acc.smtp.host == "smtp.fastmail.com"
        assert acc.smtp.port == 465
        assert acc.identity.from_addr == "Me <me@example.com>"

    def test_multi_account(self, config_file):
        path = config_file(MULTI_ACCOUNT_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "p1", "IMAP_WORK_PASS": "p2"}):
            cfg = load_config(path)

        assert set(cfg.accounts.keys()) == {"personal", "work"}
        assert cfg.accounts["work"].smtp.port == 587

    def test_folder_defaults(self, config_file):
        """If no folders: block, sensible defaults are applied."""
        path = config_file(MINIMAL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x"}):
            cfg = load_config(path)

        folders = cfg.accounts["personal"].folders
        assert folders.inbox == "INBOX"
        assert folders.sent is not None
        assert folders.drafts is not None
        assert folders.trash is not None
        assert folders.spam is not None

    def test_safety_defaults(self, config_file):
        path = config_file(MINIMAL_YAML)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x"}):
            cfg = load_config(path)

        safety = cfg.accounts["personal"].safety
        assert safety.allow_delete is False
        assert safety.allow_empty_trash is False
        assert safety.confirm_batch_threshold == 25

    def test_missing_default_account(self, config_file):
        bad = MINIMAL_YAML.replace("default_account: personal", "default_account: nonexistent")
        path = config_file(bad)
        with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "x"}):
            with pytest.raises(ValueError, match="nonexistent"):
                load_config(path)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_config_env_var(self, config_file, monkeypatch):
        path = config_file(MINIMAL_YAML)
        monkeypatch.setenv("IMAP_MCP_CONFIG", path)
        monkeypatch.setenv("IMAP_PERSONAL_PASS", "secret")
        cfg = load_config()  # no path → reads env var
        assert cfg.default_account == "personal"
