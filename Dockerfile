# ---- Builder stage: install Python deps + compile native extensions ----
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System deps for compiling native packages + uv installer
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv via official installer (avoids ghcr.io auth issues)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install Python deps (layer cached unless pyproject.toml or uv.lock change)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project --frozen 2>/dev/null || uv sync --no-dev --no-install-project


# ---- Runtime stage: slim image with only what's needed ----
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install uv to a shared location accessible by non-root user
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && cp /root/.local/bin/uv /usr/local/bin/uv
ENV PATH="/usr/local/bin:$PATH"

# Copy installed virtualenv from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Install Playwright chromium + its system deps
RUN /app/.venv/bin/python -m playwright install --with-deps chromium \
    && rm -rf /tmp/* /var/tmp/* /var/lib/apt/lists/*

# Copy application code (changes most often, so this layer is last)
COPY app/ /app/app/

# Create non-root user with a writable home for uv cache
RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
