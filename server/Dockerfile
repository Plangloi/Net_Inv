FROM python:3.12-slim

# iproute2 (ip neigh, for ARP/MAC resolution) + iputils-ping (ICMP probe to
# populate the neighbor cache before reading it). NET_RAW for raw ICMP
# sockets is in Docker's default capability set — no cap_add needed on a
# stock Docker install. If ping fails inside the container, add
# `cap_add: [NET_RAW]` to the compose service.
RUN apt-get update && apt-get install -y --no-install-recommends \
      iproute2 iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# uv = fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /srv
COPY pyproject.toml .
RUN uv pip install --system --no-cache .

COPY app ./app
COPY static ./static

ENV NETINV_DB=/data/netinv.db \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=2).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
