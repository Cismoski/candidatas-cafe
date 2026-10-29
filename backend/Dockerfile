# Imagens fixadas por digest (lista multi-arquitetura). Para atualizar:
#   docker pull python:3.13-slim && docker inspect --format '{{index .RepoDigests 0}}' python:3.13-slim
ARG PYTHON_IMAGE=python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b

FROM ${UV_IMAGE} AS uv

# --- build: dependências exatas do uv.lock, sem as de desenvolvimento -----------
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
# rasterio/pyproj trazem GDAL e PROJ nas wheels (só a libexpat vem do sistema)
RUN uv sync --frozen --no-dev --no-install-project

# --- runtime: sem uv, sem compiladores, sem root --------------------------------
FROM ${PYTHON_IMAGE}
# libexpat: a wheel do rasterio linka com a do sistema e a imagem slim não a traz
RUN apt-get update \
 && apt-get install -y --no-install-recommends libexpat1 \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /nonexistent --shell /usr/sbin/nologin app \
 && mkdir -p /data && chown app:app /data
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY app ./app
COPY config ./config
# Pré-compila o app: cada análise roda num subprocesso novo, e com
# PYTHONDONTWRITEBYTECODE ele recompilaria tudo a cada job (0,1 CPU no Render)
RUN python -m compileall -q app
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data PORT=8000
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"]
# 1 worker: fila de jobs, circuit breaker, rate limit e semáforo do chat vivem
# na memória do processo. Mais workers dividiriam esse estado.
CMD ["sh", "-c", "exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port \"$PORT\" --workers 1 --no-server-header"]
