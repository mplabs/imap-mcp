"""Tests for message reference (ref) encoding/decoding and resolution."""

import pytest

from imap_mcp.ref import Ref, parse_ref, encode_ref


class TestRef:
    def test_encode_and_parse(self):
        ref = Ref(account="personal", folder="INBOX", uidvalidity=1699999999, uid=12345)
        encoded = encode_ref(ref)
        assert encoded == "personal:INBOX:1699999999:12345"

    def test_parse_roundtrip(self):
        original = "personal:INBOX:1699999999:12345"
        ref = parse_ref(original)
        assert ref.account == "personal"
        assert ref.folder == "INBOX"
        assert ref.uidvalidity == 1699999999
        assert ref.uid == 12345
        assert encode_ref(ref) == original

    def test_parse_folder_with_delimiter(self):
        # Folders can contain dots or slashes — only first 3 colons are delimiters
        ref = parse_ref("work:INBOX.Subfolder:100:42")
        assert ref.folder == "INBOX.Subfolder"

    def test_parse_invalid_too_few_parts(self):
        with pytest.raises(ValueError, match="Invalid ref"):
            parse_ref("personal:INBOX:123")

    def test_is_ref_string(self):
        from imap_mcp.ref import is_ref
        assert is_ref("personal:INBOX:1699999999:12345") is True
        assert is_ref("<abc123@example.com>") is False
        assert is_ref("not-a-ref") is False

    def test_is_message_id(self):
        from imap_mcp.ref import is_message_id
        assert is_message_id("<abc123@example.com>") is True
        assert is_message_id("personal:INBOX:1699999999:12345") is False
