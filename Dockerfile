ARG UV_MAJOR_VERSION=0.10
ARG PYTHON_VERSION=3.12
ARG DEBIAN_VERSION=trixie

# Build the virtual environment using UV
FROM ghcr.io/astral-sh/uv:${UV_MAJOR_VERSION}-python${PYTHON_VERSION}-${DEBIAN_VERSION}-slim AS builder

# Redeclare ARG after FROM to make it available in this stage
ARG UV_COMPILE_BYTECODE=1

ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive
ENV UV_COMPILE_BYTECODE=${UV_COMPILE_BYTECODE}

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev python3-dev gcc git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Sync dependencies without installing the project itself (creates .venv)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Ensure subsequent commands use the virtual environment
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Copy application code (including .git for version detection)
COPY pyproject.toml uv.lock README.md ./
COPY flexmeasures ./flexmeasures
COPY .git ./.git
COPY .flaskenv wsgi.py ./

# Install FlexMeasures itself in the virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Install gunicorn separately since it's not a dependency of the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install gunicorn==25.0.3

# Use a separate runtime image to run the code
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} AS runtime

ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies only
# libgomp1 is required by lightgmb to open a shared object file for parallel computation
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 coinor-cbc libgomp1 curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Copy virtual environment from builder
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

# Copy application code
COPY --from=builder /app/flexmeasures ./flexmeasures
COPY --from=builder /app/.flaskenv /app/wsgi.py ./

# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# Gunicorn configuration:
# - worker-tmp-dir is set to /dev/shm instead of /tmp (default) to avoid stalls from Docker overlay filesystem
#   http://docs.gunicorn.org/en/latest/faq.html#how-do-i-avoid-gunicorn-excessively-blocking-in-os-fchmod
# - Using 2 workers to avoid health check timeouts when another request is taking a long time
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--worker-tmp-dir", "/dev/shm", \
     "--workers", "2", \
     "--threads", "4", \
     "wsgi:application"]
