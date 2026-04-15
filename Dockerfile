FROM python:3.12-slim AS build

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir ".[sieve]"

FROM python:3.12-slim

WORKDIR /app
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin/imap-mcp /usr/local/bin/imap-mcp

# Config and state are mounted at runtime — no credentials baked in.
VOLUME ["/config"]
ENV IMAP_MCP_CONFIG=/config/config.yaml

EXPOSE 8000

CMD ["imap-mcp", "--transport", "http"]
