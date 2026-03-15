# ---- Builder stage: install Python deps + compile native extensions ----
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System deps needed for compiling native Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python deps (layer cached unless pyproject.toml or uv.lock change)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project --frozen 2>/dev/null || uv sync --no-dev --no-install-project


# ---- Runtime stage: slim image with only what's needed ----
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install uv (needed to run commands via uv run)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy installed virtualenv from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Install Playwright chromium + its system deps (biggest layer, cached unless venv changes)
RUN /app/.venv/bin/python -m playwright install --with-deps chromium \
    && rm -rf /tmp/* /var/tmp/*

# Clean up apt caches left by playwright's --with-deps
RUN rm -rf /var/lib/apt/lists/*

# Copy application code (changes most often, so this layer is last)
COPY app/ /app/app/

# Create non-root user
RUN groupadd --system appuser && useradd --system --gid appuser --no-create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
