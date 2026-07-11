# syntax=docker/dockerfile:1.7

FROM python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels ".[api]"


FROM python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MDMETA_DATABASE_PATH=/data/records.sqlite \
    MDMETA_DATABASE_READ_ONLY=true \
    MDMETA_HOST=0.0.0.0 \
    MDMETA_PORT=8000 \
    MDMETA_WORKERS=1 \
    MDMETA_LOG_LEVEL=info \
    MDMETA_DATASET_SHA256=unversioned \
    MDMETA_BUILD_SHA=unknown

RUN groupadd --gid 10001 mdmeta \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin mdmeta \
    && mkdir -p /data \
    && chown mdmeta:mdmeta /data

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

USER 10001:10001
WORKDIR /app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)"]

CMD ["mdmeta-serve"]
