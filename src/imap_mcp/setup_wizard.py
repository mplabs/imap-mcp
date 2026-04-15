"""Setup wizard for imap-mcp.

Serves GET /setup (form) and POST /setup (process).

Flow:
  1. Claude Cowork triggers the OAuth /authorize endpoint.
  2. The OAuth provider redirects to /setup?oauth_state=<nonce>.
  3. User fills in IMAP/SMTP credentials + the setup key (printed to logs
     on first start).
  4. Server validates credentials live, writes config.yaml, creates an
     OAuth authorization code, and redirects back to Claude Cowork.
  5. Claude Cowork exchanges the code for an access token.  Done.

The setup key prevents strangers from configuring your server via the web.
It is generated once and persisted in ~/.local/state/imap-mcp/setup_key.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from .oauth_provider import JsonFileOAuthProvider

_SETUP_KEY_PATH = Path.home() / ".local" / "state" / "imap-mcp" / "setup_key"


# ---------------------------------------------------------------------------
# Setup key management
# ---------------------------------------------------------------------------

def load_or_create_setup_key() -> str:
    """Return the persistent setup key, creating it on first call."""
    _SETUP_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _SETUP_KEY_PATH.exists():
        return _SETUP_KEY_PATH.read_text().strip()
    key = secrets.token_urlsafe(16)
    _SETUP_KEY_PATH.write_text(key)
    return key


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>imap-mcp setup</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, sans-serif; background: #f5f5f5;
          margin: 0; padding: 2rem 1rem; color: #222; }}
  .card {{ background: #fff; max-width: 560px; margin: 0 auto;
           border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.12);
           padding: 2rem; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.4rem; }}
  .subtitle {{ color: #666; margin: 0 0 1.5rem; font-size: .9rem; }}
  .section {{ border-top: 1px solid #e5e5e5; margin: 1.25rem 0 0;
              padding-top: 1rem; }}
  .section-title {{ font-weight: 600; font-size: .85rem; text-transform: uppercase;
                    letter-spacing: .06em; color: #555; margin: 0 0 .75rem; }}
  label {{ display: block; font-size: .875rem; margin-bottom: .2rem;
           font-weight: 500; }}
  input[type=text], input[type=password], input[type=email], input[type=number] {{
    width: 100%; padding: .45rem .6rem; border: 1px solid #ccc;
    border-radius: 4px; font-size: .9rem; transition: border-color .15s; }}
  input:focus {{ outline: none; border-color: #4f7bf7; box-shadow: 0 0 0 3px rgba(79,123,247,.15); }}
  .row {{ display: grid; grid-template-columns: 1fr auto; gap: .5rem; align-items: end; }}
  .row .port-field {{ width: 80px; }}
  .checkbox-row {{ display: flex; gap: 1.5rem; margin: .5rem 0; }}
  .checkbox-row label {{ display: flex; align-items: center; gap: .35rem;
                         font-weight: 400; cursor: pointer; }}
  .error {{ background: #fff0f0; border: 1px solid #f5c5c5; border-radius: 4px;
            padding: .75rem 1rem; margin-bottom: 1rem; color: #c0392b;
            font-size: .875rem; }}
  .info {{ background: #f0f6ff; border: 1px solid #c5d8f5; border-radius: 4px;
           padding: .75rem 1rem; margin-bottom: 1rem; color: #1a4a8a;
           font-size: .875rem; }}
  button[type=submit] {{
    margin-top: 1.5rem; width: 100%; padding: .65rem 1rem;
    background: #4f7bf7; color: #fff; border: none; border-radius: 4px;
    font-size: 1rem; font-weight: 600; cursor: pointer; transition: background .15s; }}
  button[type=submit]:hover {{ background: #3b65e0; }}
  .field {{ margin-bottom: .75rem; }}
  #smtp-fields {{ margin-top: .75rem; }}
</style>
</head>
<body>
<div class="card">
  <h1>imap-mcp setup</h1>
  <p class="subtitle">Configure your mail account to use with Claude.</p>

  {alert}

  <form method="post" action="/setup">
    <input type="hidden" name="oauth_state" value="{oauth_state}">

    <div class="field">
      <label for="setup_key">Setup key
        <span style="font-weight:400;color:#888">(shown in server logs on first start)</span>
      </label>
      <input type="password" id="setup_key" name="setup_key" required
             value="{setup_key}" placeholder="Paste the key from your server logs">
    </div>

    <div class="section">
      <div class="section-title">Account</div>
      <div class="field">
        <label for="account_name">Account nickname</label>
        <input type="text" id="account_name" name="account_name" required
               value="{account_name}" placeholder="personal">
      </div>
      <div class="field">
        <label for="display_name">Your name</label>
        <input type="text" id="display_name" name="display_name" required
               value="{display_name}" placeholder="Alice Smith">
      </div>
      <div class="field">
        <label for="email">Email address</label>
        <input type="email" id="email" name="email" required
               value="{email}" placeholder="alice@example.com">
      </div>
    </div>

    <div class="section">
      <div class="section-title">IMAP (incoming mail)</div>
      <div class="field">
        <div class="row">
          <div>
            <label for="imap_host">Host</label>
            <input type="text" id="imap_host" name="imap_host" required
                   value="{imap_host}" placeholder="imap.example.com">
          </div>
          <div class="port-field">
            <label for="imap_port">Port</label>
            <input type="number" id="imap_port" name="imap_port" required
                   value="{imap_port}" placeholder="993">
          </div>
        </div>
      </div>
      <div class="checkbox-row">
        <label><input type="checkbox" name="imap_tls" value="1"
               {imap_tls_checked}> TLS (port 993)</label>
        <label><input type="checkbox" name="imap_starttls" value="1"
               {imap_starttls_checked}> STARTTLS (port 143)</label>
      </div>
      <div class="field">
        <label for="imap_username">Username</label>
        <input type="text" id="imap_username" name="imap_username" required
               value="{imap_username}" placeholder="alice@example.com">
      </div>
      <div class="field">
        <label for="imap_password">App password</label>
        <input type="password" id="imap_password" name="imap_password" required
               placeholder="Your app-specific password">
      </div>
    </div>

    <div class="section">
      <div class="section-title">SMTP (outgoing mail)</div>
      <div class="checkbox-row" style="margin-bottom:.6rem">
        <label>
          <input type="checkbox" id="smtp_same" name="smtp_same" value="1"
                 {smtp_same_checked} onchange="toggleSmtp(this)">
          Same server as IMAP (just change port)
        </label>
      </div>
      <div id="smtp-fields" style="display:{smtp_fields_display}">
        <div class="field">
          <div class="row">
            <div>
              <label for="smtp_host">Host</label>
              <input type="text" id="smtp_host" name="smtp_host"
                     value="{smtp_host}" placeholder="smtp.example.com">
            </div>
            <div class="port-field">
              <label for="smtp_port">Port</label>
              <input type="number" id="smtp_port" name="smtp_port"
                     value="{smtp_port}" placeholder="465">
            </div>
          </div>
        </div>
        <div class="checkbox-row">
          <label><input type="checkbox" name="smtp_tls" value="1"
                 {smtp_tls_checked}> TLS (port 465)</label>
          <label><input type="checkbox" name="smtp_starttls" value="1"
                 {smtp_starttls_checked}> STARTTLS (port 587)</label>
        </div>
        <div class="field">
          <label for="smtp_username">Username</label>
          <input type="text" id="smtp_username" name="smtp_username"
                 value="{smtp_username}" placeholder="alice@example.com">
        </div>
        <div class="field">
          <label for="smtp_password">App password</label>
          <input type="password" id="smtp_password" name="smtp_password"
                 placeholder="Leave blank to reuse IMAP password">
        </div>
      </div>
      <div id="smtp-port-only" style="display:{smtp_port_only_display}">
        <div class="field">
          <label for="smtp_port_same">SMTP port</label>
          <input type="number" id="smtp_port_same" name="smtp_port_same"
                 value="{smtp_port_same}" placeholder="465">
        </div>
        <div class="checkbox-row">
          <label><input type="checkbox" name="smtp_same_tls" value="1"
                 {smtp_same_tls_checked}> TLS</label>
          <label><input type="checkbox" name="smtp_same_starttls" value="1"
                 {smtp_same_starttls_checked}> STARTTLS</label>
        </div>
      </div>
    </div>

    <button type="submit">Test connection &amp; save &#8594;</button>
  </form>
</div>
<script>
function toggleSmtp(cb) {{
  document.getElementById('smtp-fields').style.display = cb.checked ? 'none' : '';
  document.getElementById('smtp-port-only').style.display = cb.checked ? '' : 'none';
}}
</script>
</body>
</html>
"""

_SUCCESS_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>imap-mcp — Setup complete</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #f5f5f5;
          margin: 0; padding: 2rem 1rem; }}
  .card {{ background: #fff; max-width: 480px; margin: 0 auto;
           border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.12);
           padding: 2rem; text-align: center; }}
  h1 {{ color: #2e7d32; }}
  p {{ color: #555; line-height: 1.6; }}
</style>
</head>
<body>
<div class="card">
  <h1>&#10003; Setup complete</h1>
  <p>Your mail account <strong>{account_name}</strong> has been configured
     successfully. You can close this window — Claude will continue
     connecting in the background.</p>
</div>
</body>
</html>
"""


def _render(template: str, **kwargs) -> str:
    return template.format(**kwargs)


def _checked(val: bool) -> str:
    return "checked" if val else ""


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def _defaults() -> dict:
    return dict(
        alert="",
        oauth_state="",
        setup_key="",
        account_name="personal",
        display_name="",
        email="",
        imap_host="",
        imap_port="993",
        imap_tls_checked=_checked(True),
        imap_starttls_checked=_checked(False),
        imap_username="",
        smtp_same_checked=_checked(True),
        smtp_fields_display="none",
        smtp_port_only_display="",
        smtp_host="",
        smtp_port="465",
        smtp_tls_checked=_checked(True),
        smtp_starttls_checked=_checked(False),
        smtp_username="",
        smtp_port_same="465",
        smtp_same_tls_checked=_checked(True),
        smtp_same_starttls_checked=_checked(False),
    )


async def handle_get(request: Request) -> Response:
    vals = _defaults()
    vals["oauth_state"] = request.query_params.get("oauth_state", "")
    return HTMLResponse(_render(_PAGE, **vals))


async def handle_post(request: Request) -> Response:
    ctx = request.state.wizard_context
    setup_key: str = ctx["setup_key"]
    auth_provider: JsonFileOAuthProvider = ctx["auth_provider"]
    config_path: Path = ctx["config_path"]

    form = await request.form()

    def f(name: str, default: str = "") -> str:
        return str(form.get(name, default)).strip()

    def cb(name: str) -> bool:
        return form.get(name) == "1"

    # --- Re-render helpers -----------------------------------------------

    def rerender(error: str) -> HTMLResponse:
        same = cb("smtp_same")
        vals = dict(
            alert=f'<div class="error">{error}</div>',
            oauth_state=f(  "oauth_state"),
            setup_key="",
            account_name=f("account_name"),
            display_name=f("display_name"),
            email=f("email"),
            imap_host=f("imap_host"),
            imap_port=f("imap_port", "993"),
            imap_tls_checked=_checked(cb("imap_tls")),
            imap_starttls_checked=_checked(cb("imap_starttls")),
            imap_username=f("imap_username"),
            smtp_same_checked=_checked(same),
            smtp_fields_display="none" if same else "",
            smtp_port_only_display="" if same else "none",
            smtp_host=f("smtp_host"),
            smtp_port=f("smtp_port", "465"),
            smtp_tls_checked=_checked(cb("smtp_tls")),
            smtp_starttls_checked=_checked(cb("smtp_starttls")),
            smtp_username=f("smtp_username"),
            smtp_port_same=f("smtp_port_same", "465"),
            smtp_same_tls_checked=_checked(cb("smtp_same_tls")),
            smtp_same_starttls_checked=_checked(cb("smtp_same_starttls")),
        )
        return HTMLResponse(_render(_PAGE, **vals), status_code=422)

    # --- Validate setup key -----------------------------------------------
    if not secrets.compare_digest(f("setup_key").encode(), setup_key.encode()):
        return rerender("Invalid setup key. Check your server logs.")

    # --- Collect fields ---------------------------------------------------
    account_name = f("account_name") or "personal"
    display_name = f("display_name")
    email = f("email")

    if not display_name or not email:
        return rerender("Name and email address are required.")

    imap_host = f("imap_host")
    imap_port = int(f("imap_port") or "993")
    imap_tls = cb("imap_tls")
    imap_starttls = cb("imap_starttls")
    imap_username = f("imap_username") or email
    imap_password = f("imap_password")

    if not imap_host or not imap_password:
        return rerender("IMAP host and password are required.")

    smtp_same = cb("smtp_same")
    if smtp_same:
        smtp_host = imap_host
        smtp_port = int(f("smtp_port_same") or "465")
        smtp_tls = cb("smtp_same_tls")
        smtp_starttls = cb("smtp_same_starttls")
        smtp_username = imap_username
        smtp_password = imap_password
    else:
        smtp_host = f("smtp_host") or imap_host
        smtp_port = int(f("smtp_port") or "465")
        smtp_tls = cb("smtp_tls")
        smtp_starttls = cb("smtp_starttls")
        smtp_username = f("smtp_username") or imap_username
        smtp_password = f("smtp_password") or imap_password

    # --- Validate IMAP credentials live -----------------------------------
    try:
        import imapclient  # type: ignore
        with imapclient.IMAPClient(
            host=imap_host,
            port=imap_port,
            ssl=imap_tls,
        ) as client:
            if imap_starttls:
                client.starttls()
            client.login(imap_username, imap_password)
            client.noop()
    except Exception as exc:
        return rerender(f"IMAP connection failed: {exc}")

    # --- Write config.yaml ------------------------------------------------
    import yaml  # type: ignore

    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config if present so we can add accounts without losing others.
    existing: dict = {}
    if config_path.exists():
        try:
            existing = yaml.safe_load(config_path.read_text()) or {}
        except Exception:
            existing = {}

    accounts: dict = existing.get("accounts", {})
    accounts[account_name] = {
        "imap": {
            "host": imap_host,
            "port": imap_port,
            "tls": imap_tls,
            "starttls": imap_starttls,
            "username": imap_username,
            "auth": {
                "method": "password",
                "secret_ref": f"inline:{imap_password}",
            },
        },
        "smtp": {
            "host": smtp_host,
            "port": smtp_port,
            "tls": smtp_tls,
            "starttls": smtp_starttls,
            "username": smtp_username,
            "auth": {
                "method": "password",
                "secret_ref": f"inline:{smtp_password}",
            },
        },
        "identity": {
            "from": f"{display_name} <{email}>",
        },
    }

    new_config: dict = {
        **existing,
        "default_account": existing.get("default_account", account_name),
        "accounts": accounts,
    }
    # Preserve server block if present
    if "server" not in new_config:
        new_config["server"] = {"auth_token": ""}

    tmp = config_path.with_suffix(".tmp")
    tmp.write_text(yaml.dump(new_config, default_flow_style=False, allow_unicode=True))
    tmp.replace(config_path)

    # --- Complete the OAuth flow ------------------------------------------
    oauth_state = f("oauth_state")
    if oauth_state:
        pending = auth_provider.pop_pending_auth(oauth_state)
        if pending is not None:
            code = auth_provider.create_auth_code(pending)
            redirect_uri = pending["redirect_uri"]
            params: dict = {"code": code}
            if pending.get("state"):
                params["state"] = pending["state"]
            return RedirectResponse(
                url=f"{redirect_uri}?{urlencode(params)}",
                status_code=302,
            )

    # No OAuth state (user visited /setup directly) — show success page.
    return HTMLResponse(_render(_SUCCESS_PAGE, account_name=account_name))


# ---------------------------------------------------------------------------
# Starlette route factory
# ---------------------------------------------------------------------------

def create_setup_routes(
    auth_provider: JsonFileOAuthProvider,
    config_path: Path,
    setup_key: str,
) -> list[Route]:
    """Return the /setup GET and POST routes, with shared context injected."""

    wizard_context = {
        "auth_provider": auth_provider,
        "config_path": config_path,
        "setup_key": setup_key,
    }

    async def _inject(request: Request, call_next=None):
        request.state.wizard_context = wizard_context
        if call_next:
            return await call_next(request)

    async def get_handler(request: Request) -> Response:
        request.state.wizard_context = wizard_context
        return await handle_get(request)

    async def post_handler(request: Request) -> Response:
        request.state.wizard_context = wizard_context
        return await handle_post(request)

    return [
        Route("/setup", endpoint=get_handler, methods=["GET"]),
        Route("/setup", endpoint=post_handler, methods=["POST"]),
    ]
