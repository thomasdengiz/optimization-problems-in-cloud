FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

# Hugging Face Spaces runs containers as a non-root user with id 1000
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

# Install dependencies first so Docker can cache this layer between code changes
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser solver ./solver
COPY --chown=appuser:appuser data/power_plants.json data/entsoe_2023.json ./data/

USER appuser
EXPOSE 7860

# Shell form so ${PORT} is expanded (7860 on Hugging Face, overridable locally)
CMD ["sh", "-c", "uvicorn solver.api:app --host 0.0.0.0 --port ${PORT}"]
