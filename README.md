# imap-mcp

An MCP server that gives Claude agents full access to any IMAP mailbox (plus SMTP for sending). Works with Claude Code (stdio) and Claude Cowork (HTTP).

## Quick start

### Claude Code (local, stdio)

1. **Install**
   ```bash
   pip install imap-mcp
   # or from source:
   pip install .
   ```

2. **Create a config file** at `~/.config/imap-mcp/config.yaml`:
   ```yaml
   default_account: personal

   accounts:
     personal:
       imap:
         host: imap.fastmail.com
         port: 993
         tls: true
         username: you@example.com
         auth:
           method: password
           secret_ref: "env:IMAP_PASS"
       smtp:
         host: smtp.fastmail.com
         port: 465
         tls: true
         username: you@example.com
         auth:
           method: password
           secret_ref: "env:IMAP_PASS"
       identity:
         from: "Your Name <you@example.com>"
   ```

3. **Add to Claude Code** (`~/.claude/mcp_settings.json`):
   ```json
   {
     "mcpServers": {
       "imap": {
         "command": "imap-mcp",
         "env": {
           "IMAP_PASS": "your-app-password"
         }
       }
     }
   }
   ```
   Or use a custom config path:
   ```json
   {
     "mcpServers": {
       "imap": {
         "command": "imap-mcp",
         "args": ["--config", "/path/to/config.yaml"],
         "env": { "IMAP_PASS": "your-app-password" }
       }
     }
   }
   ```

---

### Claude Cowork (remote, HTTP + Docker)

1. **Create a config directory** and start the server:
   ```bash
   mkdir -p config
   docker compose up -d
   ```
   No config file needed — the setup wizard creates it.

2. **Note the setup key** printed in the server logs:
   ```
   docker compose logs imap-mcp
   # look for:  imap-mcp setup key: abc123...
   ```

3. **Add to Claude Cowork** — paste `https://your-server:8000/mcp` as the server URL. Claude Cowork will open a browser window to the setup wizard automatically.

4. **Fill in your mail credentials** and paste the setup key when prompted. The server tests the connection live and saves the config. Done — Claude Cowork is connected.

   > **TLS required for public deployments.** The server itself does not terminate TLS. Put nginx, Caddy, or a load balancer in front. See [TLS with a reverse proxy](#tls-with-a-reverse-proxy).
   >
   > For a public server, also set `issuer_url` in the server config block:
   > ```yaml
   > server:
   >   issuer_url: "https://your-server.example.com"
   > ```

---

## Config file reference

The config file is YAML. Its path is `~/.config/imap-mcp/config.yaml` by default, overridable with the `IMAP_MCP_CONFIG` environment variable or the `--config` flag.

### Top-level keys

```yaml
default_account: personal   # which account to use when none is specified

server:                     # HTTP transport settings (optional; only for --transport http)
  host: 0.0.0.0             # default
  port: 8000                # default
  auth_token: "env:IMAP_MCP_TOKEN"   # required for HTTP; see Secrets below
  request_timeout_s: 60     # default

accounts:
  <name>:
    imap: ...
    smtp: ...
    identity: ...
    folders: ...            # optional
    safety: ...             # optional
    rate_limit: ...         # optional
    resolver: ...           # optional
    attachment: ...         # optional
    sieve: ...              # optional
```

### IMAP / SMTP

```yaml
imap:
  host: imap.fastmail.com
  port: 993
  tls: true                 # implicit TLS (port 993). Use starttls: true for port 143/587.
  username: you@example.com
  auth:
    method: password        # or app_password (alias, stored separately for clarity)
    secret_ref: "env:IMAP_PASS"

smtp:
  host: smtp.fastmail.com
  port: 465
  tls: true
  username: you@example.com
  auth:
    method: password
    secret_ref: "env:SMTP_PASS"
```

Common provider settings:

| Provider | IMAP host/port | SMTP host/port | Notes |
|----------|---------------|----------------|-------|
| Fastmail | `imap.fastmail.com:993` | `smtp.fastmail.com:465` | App password required |
| iCloud | `imap.mail.me.com:993` | `smtp.mail.me.com:587` (starttls) | App password required |
| Outlook/M365 | `outlook.office365.com:993` | `smtp.office365.com:587` (starttls) | App password or OAuth |
| Gmail | `imap.gmail.com:993` | `smtp.gmail.com:465` | App password required; enable IMAP in settings |
| Self-hosted (Dovecot) | your host:993 | your host:465 | TLS cert needed |

### Identity

```yaml
identity:
  from: "Your Name <you@example.com>"
  reply_to: null            # optional
```

### Folder mapping (optional)

Autodetected from IMAP SPECIAL-USE flags. Override only if your server uses non-standard names.

```yaml
folders:
  inbox: INBOX
  sent: Sent
  drafts: Drafts
  trash: Trash
  spam: Junk
  archive: Archive
```

### Safety (optional)

```yaml
safety:
  allow_delete: false           # hard deletes require explicit true + hard=true in call
  allow_empty_trash: false      # empty_trash requires explicit true + confirm=true in call
  confirm_batch_threshold: 25   # batch ops over N messages require confirm=true
```

### Rate limiting (optional)

```yaml
rate_limit:
  max_ops_per_minute: 60    # token bucket; each IMAP command consumes one token
```

### Resolver (optional)

```yaml
resolver:
  max_search_folders: 10    # cap for cross-folder message_id lookup
```

### Attachment (optional)

```yaml
attachment:
  max_size_mb: 50           # reject attachment downloads larger than this
```

### Sieve / ManageSieve (optional)

Only needed if you want `list_sieve_scripts` / `put_sieve_script` tools. Your mail server must support ManageSieve (RFC 5804).

```yaml
sieve:
  host: imap.fastmail.com
  port: 4190
  username: you@example.com
  auth:
    method: password
    secret_ref: "env:IMAP_PASS"
```

---

## Secrets

Passwords and tokens are **never stored in plaintext** in the config. The `secret_ref` field uses a URI scheme:

| Scheme | Example | How it works |
|--------|---------|--------------|
| `env:<VAR>` | `env:IMAP_PASS` | Reads `$IMAP_PASS` from the environment |
| `keyring:<service>/<user>` | `keyring:imap-mcp/personal` | Reads from the OS keyring (macOS Keychain, GNOME Keyring, Windows Credential Vault) |

**Store a secret in the OS keyring:**
```bash
python -c "import keyring; keyring.set_password('imap-mcp', 'personal', 'your-password')"
```
Then use `secret_ref: "keyring:imap-mcp/personal"` in the config.

**Environment variables** are the easiest option for Docker deployments. Pass them via `docker compose` or your orchestrator's secret management.

---

## Multiple accounts

Add as many accounts as you need. All tools accept an optional `account` parameter to target a specific one.

```yaml
default_account: personal

accounts:
  personal:
    imap: { host: imap.fastmail.com, port: 993, tls: true, username: me@personal.com, auth: { method: password, secret_ref: "env:PERSONAL_PASS" } }
    smtp: { host: smtp.fastmail.com, port: 465, tls: true, username: me@personal.com, auth: { method: password, secret_ref: "env:PERSONAL_PASS" } }
    identity: { from: "Me <me@personal.com>" }

  work:
    imap: { host: outlook.office365.com, port: 993, tls: true, username: me@work.com, auth: { method: password, secret_ref: "env:WORK_PASS" } }
    smtp: { host: smtp.office365.com, port: 587, tls: false, starttls: true, username: me@work.com, auth: { method: password, secret_ref: "env:WORK_PASS" } }
    identity: { from: "Me <me@work.com>" }
```

---

## CLI flags

```
imap-mcp [--transport stdio|http] [--host HOST] [--port PORT] [--config PATH]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--transport` | `stdio` | `stdio` for Claude Code; `http` for Claude Cowork |
| `--host` | `0.0.0.0` | Bind host (HTTP only; overrides config) |
| `--port` | `8000` | Bind port (HTTP only; overrides config) |
| `--issuer-url` | `http://host:port` | Public OAuth issuer URL; set to your HTTPS URL in production |
| `--config` | `~/.config/imap-mcp/config.yaml` | Config file path (created by setup wizard if absent) |

---

## Docker deployment

### Build and run

```bash
mkdir -p config
docker compose up -d

# Get the setup key from the logs
docker compose logs imap-mcp | grep "setup key"
```

Then add `https://your-server:8000/mcp` to Claude Cowork. The browser-based setup wizard handles the rest.

### docker-compose.yml

The included `docker-compose.yml` mounts the config directory read-write so the setup wizard can create `config.yaml` on first start.

### TLS with a reverse proxy

The server does not terminate TLS itself. For any public deployment, put a TLS-terminating proxy in front. Example with Caddy:

```
your-server.example.com {
    reverse_proxy localhost:8000
}
```

With nginx:
```nginx
server {
    listen 443 ssl;
    server_name your-server.example.com;
    ssl_certificate     /etc/ssl/certs/your-cert.pem;
    ssl_certificate_key /etc/ssl/private/your-key.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Authorization $http_authorization;
        proxy_pass_header Authorization;
    }
}
```

---

## Testing your connection

Once configured, ask Claude: *"Test my mail connection"* — or call `test_connection` directly. It runs an IMAP LOGIN/NOOP and SMTP EHLO independently and reports results for each.

---

## Troubleshooting

**`Environment variable 'X' not set`** — the env var referenced in `secret_ref` is not exported. Check that the variable is set in the shell or Docker env.

**`AUTH_FAILED`** — wrong password, or your provider requires an app password (not your account password). Gmail, iCloud, and Outlook all require app-specific passwords when 2FA is enabled.

**`CONNECTION_FAILED`** — wrong host/port, firewall blocking the connection, or TLS mismatch. Check that `tls: true` matches your port (993/465 = implicit TLS; 143/587 = `starttls: true`).

**`RATE_LIMITED`** — the configured `max_ops_per_minute` was exceeded. Increase it or space out agent calls.

**Bearer token 401 on HTTP transport** — make sure the token in the `Authorization: Bearer <token>` header exactly matches `server.auth_token`. Check for trailing newlines if you generated it with `echo`.
