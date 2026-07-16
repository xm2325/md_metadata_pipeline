FROM python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BUILD_CONSTRAINT=/build/constraints/build.txt \
    PIP_CONSTRAINT=/build/constraints/build.txt
WORKDIR /build

COPY pyproject.toml README.md ./
COPY constraints ./constraints
COPY scripts/check_runtime_lock.py ./scripts/check_runtime_lock.py
COPY src ./src
RUN python scripts/check_runtime_lock.py \
    && python -m pip wheel \
        --constraint constraints/runtime.txt \
        --wheel-dir /wheels \
        ".[api]" \
    && python scripts/check_runtime_lock.py --wheel-dir /wheels


FROM python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MDMETA_ENV=production \
    MDMETA_DATABASE_PATH=/data/records.sqlite \
    MDMETA_DATABASE_READ_ONLY=true \
    MDMETA_HOST=0.0.0.0 \
    MDMETA_PORT=8000 \
    MDMETA_WORKERS=1 \
    MDMETA_LOG_LEVEL=info \
    MDMETA_ALLOWED_HOSTS=127.0.0.1,localhost \
    MDMETA_PROXY_HEADERS=true \
    MDMETA_FORWARDED_ALLOW_IPS=127.0.0.1 \
    MDMETA_LIMIT_CONCURRENCY=100 \
    MDMETA_BACKLOG=128 \
    MDMETA_TIMEOUT_KEEP_ALIVE=5 \
    MDMETA_TIMEOUT_GRACEFUL_SHUTDOWN=25 \
    MDMETA_ENABLE_DOCS=false \
    MDMETA_DATASET_SHA256=unversioned \
    MDMETA_BUILD_SHA=unknown

RUN groupadd --gid 10001 mdmeta \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin mdmeta \
    && mkdir -p /data \
    && chown mdmeta:mdmeta /data

COPY --from=builder /wheels /wheels
COPY pyproject.toml constraints/runtime.txt scripts/check_runtime_lock.py /tmp/lockcheck/
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl \
    && python /tmp/lockcheck/check_runtime_lock.py \
        --constraints /tmp/lockcheck/runtime.txt \
        --pyproject /tmp/lockcheck/pyproject.toml \
        --check-installed \
    && python -m pip check \
    && rm -rf /wheels /tmp/lockcheck

USER 10001:10001
WORKDIR /app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)"]

CMD ["mdmeta-serve"]
