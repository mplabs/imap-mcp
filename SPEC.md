# imap-mcp — Specification

A Model Context Protocol (MCP) server that exposes a generic IMAP mailbox (plus
SMTP for outbound) to a Claude agent. Feature parity with the reference Gmail
MCP server ([GongRzhe/Gmail-MCP-Server]), but adapted to vanilla IMAP semantics:
**folders** instead of labels, **flags** instead of system labels, **Sieve**
(optional) instead of Gmail filters.

Target runtime: local process, spoken to over stdio by a Claude Code / Cowork
agent. No hosted service, no shared state.

[GongRzhe/Gmail-MCP-Server]: https://github.com/GongRzhe/Gmail-MCP-Server

---

## 1. Goals

1. Let a Claude agent read, search, triage, move, flag, draft, and send mail
   against any standards-compliant IMAP + SMTP provider (self-hosted Dovecot /
   Cyrus, Fastmail, iCloud, Outlook/M365, Gmail-via-IMAP, etc.).
2. Match the Gmail MCP server's surface area 1:1 where the concept translates,
   and provide clean generic replacements where it doesn't.
3. Behave predictably for agent use: small, well-described tools; stable IDs;
   pagination; structured errors with recovery hints.
4. Be safe by default: destructive operations are opt-in per account, dry-run
   on batch ops, and there is always an audit log.

## 2. Non-goals

- No web UI, no hosted multi-tenant mode.
- No re-implementing a mail client (threading UI, rich rendering, calendaring).
- No provider-specific features that leak Gmail-isms (e.g. `X-GM-LABELS`) into
  the core API. A thin `gmail_extras` module may expose them when the server
  detects a Gmail IMAP session, but agents should not rely on it.
- No push notifications in v1. `IDLE` support is a v2 stretch goal.

## 3. Architecture

```
┌──────────────┐   stdio/MCP    ┌───────────────────────────────────────┐
│ Claude agent │ ─────────────► │ imap-mcp server                       │
└──────────────┘                │  ├── tool dispatcher (dict-based)     │
                                │  ├── error boundary (ImapMcpError)    │
                                │  ├── Context(pool, registry,          │
                                │  │         audit, resolver)           │
                                │  ├── account registry                 │
                                │  ├── IMAP connection manager          │
                                │  │   (imapclient, per-call)           │
                                │  ├── MessageResolver (session cache + │
                                │  │   folder-scan fallback, cap=10)    │
                                │  ├── SMTP client (aiosmtplib)         │
                                │  ├── MIME builder/parser (stdlib)     │
                                │  ├── Sieve client (optional)          │
                                │  └── local cache (UIDVALIDITY map)    │
                                └───────────────────────────────────────┘
```

- **Language:** Python 3.11+.
- **MCP framework:** the official `mcp` Python SDK.
- **Transport:** stdio only in v1.
- **Concurrency:** one `IMAPClient` per tool call; login → select → work →
  logout. A future LRU pool is a v2 concern.
- **Context object:** a single `Context(pool, registry, audit, resolver)`
  dataclass is constructed at server startup and threaded through every tool
  call. Tools never reach into the server for global state.
- **State:** mostly stateless. The only durable state is a small JSON file
  mapping `(account, folder) → UIDVALIDITY` so the server can detect when UIDs
  have been invalidated between sessions.

## 4. Configuration

Config is a single YAML file, path overridable via `IMAP_MCP_CONFIG` env var
(default `~/.config/imap-mcp/config.yaml`). Secrets are **not** inlined —
they're fetched from the OS keyring (`keyring` pkg) or a named env var.

```yaml
default_account: personal

accounts:
  personal:
    imap:
      host: imap.fastmail.com
      port: 993
      tls: true
      username: me@example.com
      auth:
        method: password         # password | app_password | xoauth2 (v1.1)
        secret_ref: keyring:imap-mcp/personal  # or env:IMAP_PERSONAL_PASS
    smtp:
      host: smtp.fastmail.com
      port: 465
      tls: true                  # implicit TLS; use starttls: true for 587
      username: me@example.com
      auth:
        method: password
        secret_ref: keyring:imap-mcp/personal
    identity:
      from: "Me <me@example.com>"
      reply_to: null
    folders:
      # Optional overrides; server autodetects via SPECIAL-USE (RFC 6154).
      inbox: INBOX
      sent: Sent
      drafts: Drafts
      trash: Trash
      spam: Junk
      archive: Archive
    safety:
      allow_delete: false        # expunge requires explicit true
      allow_empty_trash: false
      confirm_batch_threshold: 25  # batch ops over N rows require confirm=true
    rate_limit:
      max_ops_per_minute: 60   # per-account token bucket; each IMAP command
                                # or SMTP send consumes one token
    resolver:
      max_search_folders: 10   # cap for cross-folder message_id lookup
    attachment:
      max_size_mb: 50          # reject downloads larger than this

  work:
    imap: { ... }
    smtp: { ... }
```

All tools accept an optional `account` parameter. If omitted, `default_account`
is used.

## 5. Authentication

Supported auth methods per account:

| Method         | IMAP | SMTP | Notes                                             |
|----------------|:----:|:----:|---------------------------------------------------|
| `password`     |  ✔   |  ✔   | Plain LOGIN over TLS. Fine for Dovecot/Fastmail.  |
| `app_password` |  ✔   |  ✔   | Alias of `password`; different secret ref so a UI can label it clearly. |
| `xoauth2`      |  —   |  —   | **v1.1 stub — not implemented in v1.** Config key accepted and validated; tools return `NOT_CONFIGURED` at runtime. |

No interactive OAuth flow in v1 — the user pastes a refresh token into the
keyring themselves. A `imap-mcp auth` CLI subcommand for first-time OAuth is a
v1.1 feature.

## 6. Core concepts, and how they differ from Gmail

| Gmail concept        | IMAP concept in this server                   | Consequence                                 |
|----------------------|-----------------------------------------------|---------------------------------------------|
| Label (many-to-many) | **Folder** (one-to-one, hierarchical)         | "Adding a label" = **copying** to folder; "moving" = copy + flag `\Deleted` + expunge in source. |
| System label (INBOX, STARRED, UNREAD, IMPORTANT) | **Flag** (`\Seen`, `\Flagged`, `\Answered`, keyword `$Important`) | Exposed via dedicated flag tools, not folder tools. |
| `in:inbox is:unread` search | IMAP `SEARCH` criteria (RFC 3501 §6.4.4) | Tool accepts a raw IMAP search string **or** a `gmail_raw` string (Gmail IMAP only). |
| Message ID (Gmail) | Stable `Message-ID` header + `(folder, UIDVALIDITY, UID)` tuple | All tools accept either; server resolves using `MessageResolver`. |
| Thread ID            | `References`/`In-Reply-To` header chain       | Best-effort; no server-side thread tool in v1. |
| Filters              | **Sieve** via ManageSieve (RFC 5804), optional | Only enabled if server advertises `SIEVE` capability. |

### 6.1 Message identifiers

The server exposes two ID forms and accepts both everywhere a message is
referenced:

- **`message_id`** — the RFC 5322 `Message-ID` header value, e.g.
  `<abc123@example.com>`. Stable across folder moves. Preferred for agent use.
- **`ref`** — a tuple string `"<account>:<folder>:<uidvalidity>:<uid>"`, e.g.
  `personal:INBOX:1699999999:12345`. The account field is the **literal account
  name** from config; it takes precedence over the `account` call parameter when
  resolving. Fast within a session, but invalidated by server-side
  expunge/rename.

**Resolution strategy (`MessageResolver`):**

1. If the id looks like a `ref` (4+ colon-separated fields ending in two
   integers), parse and return it directly.
2. If the id looks like a `message_id` (angle-bracket delimited), check the
   session-local cache (`dict[str, (folder, uid, uidvalidity)]`). The cache is
   populated automatically whenever messages are fetched.
3. On a cache miss, search up to `resolver.max_search_folders` subscribed
   folders (default 10) using `SEARCH HEADER Message-ID <value>`. Raise
   `MESSAGE_NOT_FOUND` after exhausting the cap.

**STALE_REF recovery:** when a tool returns `STALE_REF`, the agent should
re-call `list_messages` or `search_emails` to obtain fresh refs for the same
messages. The `Message-ID` header value from the stale result remains valid as
an input to any tool — the resolver will search for it.

## 7. Tool surface

Each tool below lists its Gmail MCP counterpart for traceability. Unless noted,
every tool accepts optional `account: string`.

### 7.1 Messaging — send & draft

#### `send_email`
Parity with Gmail's `send_email`. Builds a MIME message and sends via SMTP,
then `APPEND`s a copy to the configured `sent` folder with `\Seen` set.

The server **always** generates `Message-ID` (via `email.utils.make_msgid`)
and `Date` (via `email.utils.formatdate`) headers if the caller omits them.
This satisfies RFC 5321 and ensures sent messages are threadable.

- `to: string[]`
- `cc: string[]` (optional)
- `bcc: string[]` (optional)
- `subject: string`
- `body: string` (plain text; sent as bare `text/plain` when no HTML or
  attachments present)
- `html: string` (optional; sent as `multipart/alternative` with `text/plain`)
- `attachments: { path: string, filename?: string, mime?: string }[]`
- `in_reply_to: string` (optional `message_id`; sets `In-Reply-To`)
- `references: string` (optional; the original thread's `References` chain.
  When provided, the final `References` header is `references + " " + in_reply_to`)
- `headers: Record<string, string>` (optional extra headers)

#### `save_draft`
Replaces Gmail's `draft_email`. Same parameters as `send_email`, but the
message is `APPEND`ed to the `drafts` folder with the `\Draft` flag and never
sent.

**Returns** `{ success: true, ref: string|null, message_id: string, account: string, folder: string }`.

To obtain the `ref` after APPEND: use the `APPENDUID` response code from
UIDPLUS (RFC 4315) when available; fall back to `SEARCH HEADER Message-ID
<value>` immediately after append on servers without UIDPLUS.

### 7.2 Reading

#### `read_email`
Parity with Gmail's `read_email`. Fetches headers, body (text + html parts),
flags, folder, and an attachment manifest (filename, size, mime, part id).

- `id: string` (a `message_id` or `ref`)
- `include_raw: boolean` (default `false`; when true returns full RFC 822)

#### `download_attachment`
Parity with Gmail's `download_attachment`.

- `id: string`
- `part_id: string` (from the manifest returned by `read_email`)
- `save_to: string` (absolute path; `{filename}` token supported)

**Safety:** the resolved path must be absolute. The download is rejected if the
attachment size exceeds `attachment.max_size_mb` (default 50 MB). The server
does not restrict destination directory beyond requiring an absolute path; the
MCP permission prompt covers this.

### 7.3 Search & list

#### `search_emails`
Parity with Gmail's `search_emails`, but with generic IMAP semantics.

- `query`: one of
  - `{ raw: string }` — passed directly to IMAP `SEARCH`. Example:
    `"UNSEEN SINCE 1-Jan-2026 FROM \"alice@example.com\""`. See RFC 3501
    §6.4.4 for full syntax.
  - `{ gmail_raw: string }` — only valid for Gmail IMAP; uses `X-GM-RAW`.
- `folder: string` (optional; when omitted, fans out across all subscribed
  folders capped at `resolver.max_search_folders`; defaults to `INBOX` when
  provided)
- `limit: number` (default 50, max 500)
- `cursor: string` (opaque UID-based token; see Pagination below)
- `order: "newest" | "oldest"` (default `newest`)

**Pagination:** the `cursor` is UID-based, not offset-based. For `newest` order
the server returns UIDs in descending order; `next_cursor` encodes the smallest
UID on the current page. On the next call, the server returns UIDs strictly
less than that value. This survives message insertions and deletions between
pages. Cursor format: `"uid:<N>"` (opaque to callers; always treat as a string).

Returns `{ results: MessageSummary[], next_cursor?: string }` where
`MessageSummary` contains `ref`, `message_id`, `folder`, `from`, `to`,
`subject`, `date`, `flags`, `size`, `snippet` (first 200 chars of text body).

#### `list_messages`
Convenience: same as `search_emails` with an empty query. Useful for "show me
the last 20 in Inbox".

- `folder: string` (default `INBOX`)
- `limit`, `cursor`, `order` as above

### 7.4 Flags (replaces Gmail system-label management)

#### `set_flags`
- `id: string`
- `add: string[]` (e.g. `["\\Seen", "\\Flagged", "$Label1"]`)
- `remove: string[]`

#### `mark_read` / `mark_unread` / `star` / `unstar`
Thin wrappers around `set_flags` for ergonomics. Each takes `id` (or
`ids: string[]` for batch).

### 7.5 Folder moves (replaces Gmail label add/remove on a message)

#### `move_email`
- `id: string`
- `to_folder: string`
- Behavior: `COPY` to `to_folder`, set `\Deleted` on source, `EXPUNGE` the
  source (or `UID EXPUNGE` when `UIDPLUS` is available).

#### `copy_email`
- `id: string`
- `to_folder: string`

### 7.6 Deletion

#### `delete_email`
- `id: string`
- `hard: boolean` (default `false`)

If `safety.allow_delete=false` (default) → moves to `trash` folder.
If `safety.allow_delete=true` and caller passes `hard=true` → sets `\Deleted`
and expunges.

#### `empty_trash`
- `account: string`
- Requires `safety.allow_empty_trash=true`, plus `confirm: true` in the call.

### 7.7 Batch operations

Each batch tool accepts `ids: string[]` (mix of `message_id` and `ref` OK). If
`len(ids) > safety.confirm_batch_threshold`, the call must include
`confirm: true` or it returns `CONFIRMATION_REQUIRED`. All batches default to
`dry_run: false`; passing `dry_run: true` returns the would-be effect per id
without mutating. The `dry_run` check is evaluated before the confirm
threshold, so a large dry-run batch never requires `confirm: true`.

- `batch_set_flags` — parity with `batch_modify_emails`.
- `batch_move` — parity with the folder side of `batch_modify_emails`.
- `batch_delete` — parity with `batch_delete_emails`.

Implementation groups IDs by `(account, folder, uidvalidity)` using a tuple
key (not a colon-delimited string) and issues `UID STORE` for each group.

### 7.8 Folders (replaces Gmail label CRUD)

#### `list_folders`
Returns name, delimiter, flags (including `\Noselect`, `\HasChildren`,
`\Trash`, `\Sent`, …), subscribed state, and message counts.

#### `create_folder`
`name: string`.

#### `rename_folder`
`from_name: string`, `to_name: string`.

#### `delete_folder`
`name: string`. Refuses to delete folders marked special-use unless
`force: true`. The protected set is derived from IMAP SPECIAL-USE flags
(RFC 6154); `INBOX` is always protected regardless of flags.

#### `get_or_create_folder`
`name: string`. Returns `{ name, created: bool }`.

#### `subscribe_folder` / `unsubscribe_folder`
`name: string`.

#### `folder_status`
`name: string`. Returns `{ name, exists, unseen, recent }`.

### 7.9 Sieve (optional — replaces Gmail filters)

Loaded only if ManageSieve is available. The account needs a `sieve:` block
with host/port/auth. If not configured, these tools return `NOT_CONFIGURED`.

- `list_sieve_scripts` — analog of `list_filters`.
- `get_sieve_script(name)` — analog of `get_filter`.
- `put_sieve_script(name, script, dry_run?)` — creates/updates; validates via
  `CHECKSCRIPT` first. `dry_run: true` validates without uploading.
- `activate_sieve_script(name)` — at most one active.
- `delete_sieve_script(name)` — analog of `delete_filter`.

### 7.10 Administrative

- `list_accounts` — returns configured accounts and which capabilities each
  server advertises.
- `test_connection(account)` — LOGIN / NOOP / LOGOUT round-trip for IMAP;
  EHLO / QUIT round-trip for SMTP. Surfaces both auth failures independently.

## 8. Resources (MCP)

- `imap-mcp://accounts` — JSON list of configured accounts (no secrets).
- `imap-mcp://{account}/folders` — folder tree snapshot for the given account.
- `imap-mcp://{account}/capabilities` — object with keys `imap` (string[])
  and `smtp` (string[]) listing raw capability/EHLO tokens from the server.

## 9. Prompts (MCP)

- `triage_inbox` — "Walk my inbox, summarize, propose moves/flags, await
  confirmation before any write." Uses `search_emails` + `folder_status`.
- `compose_reply` — given a `message_id`, draft a reply into Drafts.
- `unsubscribe_sweep` — find list mail, extract `List-Unsubscribe` headers,
  report (never auto-click).

## 10. Errors

All tool errors are structured:

```json
{
  "code": "STALE_REF",
  "message": "UIDVALIDITY changed for INBOX",
  "retriable": true,
  "recovery": "Re-list the folder to obtain fresh refs, or use the Message-ID."
}
```

Defined codes: `AUTH_FAILED`, `CONNECTION_FAILED`, `FOLDER_NOT_FOUND`,
`MESSAGE_NOT_FOUND`, `STALE_REF`, `PERMISSION_DENIED` (from safety config),
`CONFIRMATION_REQUIRED`, `NOT_CONFIGURED`, `PROTOCOL_ERROR`, `TIMEOUT`,
`RATE_LIMITED`.

**Error boundary:** all `ImapMcpError` subclass exceptions raised by tool
implementations are caught at the dispatcher level and returned as structured
JSON in the tool result. Unhandled exceptions (programming errors) are allowed
to propagate and surface as MCP framework errors.

**Cross-folder search:** when `folder` is omitted from `search_emails`, the
server fans out to subscribed folders. The fan-out is capped at
`resolver.max_search_folders` (default 10). If the message is not found within
the cap, `MESSAGE_NOT_FOUND` is returned with a `recovery` hint suggesting a
`folder` be specified.

## 11. Safety & auditing

- **Destructive gates** (`delete_email hard=true`, `empty_trash`, large
  batches) require both account-level config and a per-call `confirm: true`.
- **Append-only audit log** at `~/.local/state/imap-mcp/audit.log` (JSONL).
- **Rate limiting** per account: a token bucket with capacity
  `rate_limit.max_ops_per_minute` (default 60). Each IMAP command (login,
  select, fetch, store, copy, expunge) and each SMTP send consumes one token.
  Exhausting the bucket returns `RATE_LIMITED` (retriable).
- **Dry-run** supported on all batch tools and on Sieve `put_sieve_script`.

## 12. Dependencies

```
mcp                >= 1.0
imapclient         >= 3.0
aiosmtplib         >= 3.0
keyring            >= 25
pyyaml             >= 6
# Optional:
managesieve        # only pulled in when Sieve is configured
```

## 13. Testing

- **Unit tests** with `pytest` using a fake `IMAPClient` via
  monkeypatching for tool logic.
- **Integration tests** against a disposable Dovecot container
  (`ghcr.io/dovecot/dovecot`) spun up by `docker-compose.test.yml`.
- **Contract tests** assert Gmail-MCP parity (`tests/test_parity.py`).

## 14. Milestones

- **M0 — scaffolding.** Config, account registry, stdio MCP server with
  `list_accounts` + `test_connection` only.
- **M1 — read path.** `list_folders`, `folder_status`, `list_messages`,
  `search_emails`, `read_email`, `download_attachment`.
- **M2 — write path.** `set_flags` + wrappers, `move_email`, `copy_email`,
  `delete_email`, folder CRUD. Audit log + safety gates.
- **M3 — outbound.** `send_email`, `save_draft`.
- **M4 — batch + parity.** `batch_*` tools, `get_or_create_folder`, parity
  table green.
- **M5 — Sieve (optional).** ManageSieve client + tools.
- **M6 — polish.** Resources, starter prompts, dict dispatch, error boundary,
  Context object, MessageResolver, docs.

## 15. Open questions

1. **Thread assembly.** Worth a v2 `read_thread` tool that walks `References`?
2. **IDLE / push.** Stretch goal. Needs a long-lived connection outside the
   stdio request/response loop.
3. **xoauth2 implementation.** Which OAuth library? Token refresh strategy?
   Deferred to v1.1.
