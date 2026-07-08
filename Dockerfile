FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY login_setup.py ./

RUN pip install --no-cache-dir .

# Non-root user; HOME=/data puts the file-fallback session store
# (~/.monarch-mcp-server/token) on the persistent volume.
RUN useradd --create-home --uid 1000 monarch \
    && mkdir -p /data \
    && chown monarch:monarch /data
ENV HOME=/data \
    MONARCH_MCP_MODE=serve \
    MONARCH_MCP_HOST=0.0.0.0 \
    MONARCH_MCP_PORT=8000
USER monarch
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

ENTRYPOINT ["monarch-mcp-server"]
CMD ["serve"]
