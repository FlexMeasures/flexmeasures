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
ENV UV_LINK_MODE=copy

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev python3-dev gcc git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Sync dependencies without installing the project itself (creates .venv)
# --no-dev excludes the dev dependency-group (mypy, black, flake8, ...).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Ensure subsequent commands use the virtual environment
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Copy application code (including .git for version detection)
COPY pyproject.toml uv.lock README.md ./
COPY flexmeasures ./flexmeasures
COPY .git ./.git
COPY .flaskenv wsgi.py ./

# Install FlexMeasures itself in the virtual environment. Released images pass
# their tag-derived version explicitly because the partial tracked working tree
# copied above appears dirty to hatch-vcs. An empty value preserves Git-derived
# versions for local builds.
ARG FLEXMEASURES_VERSION=
RUN --mount=type=cache,target=/root/.cache/uv \
    SETUPTOOLS_SCM_PRETEND_VERSION="${FLEXMEASURES_VERSION}" \
    uv sync --frozen --reinstall-package flexmeasures --no-dev

# Install gunicorn separately since it's not a dependency of the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install gunicorn==25.0.3

# sktime (and its scikit-base dependency) ship docs/ and examples/ as stray top-level directories. See: https://github.com/sktime/sktime/issues/10891
RUN rm -rf "${VIRTUAL_ENV}"/lib/python*/site-packages/docs \
           "${VIRTUAL_ENV}"/lib/python*/site-packages/examples

# Most wheels ship their compiled extensions unstripped, carrying symbol tables and debug info that nothing needs at runtime.
# Stripping them here keeps ~130 MB out of the runtime image, which copies only the result of this stage.
# --strip-unneeded leaves everything that dynamic linking uses, so the extensions stay loadable.
# binutils only reaches this stage as a transitive of the gcc install above, so check for strip explicitly:
# the trailing `|| true` is there for individual files strip cannot handle, and would otherwise hide a missing binutils.
RUN command -v strip > /dev/null || { \
        echo "strip not found: the builder stage needs binutils" >&2; exit 1; \
    }; \
    find "${VIRTUAL_ENV}" \( -name '*.so' -o -name '*.so.*' \) -type f \
    -exec strip --strip-unneeded {} + 2>/dev/null || true

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
