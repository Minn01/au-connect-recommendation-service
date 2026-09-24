# Recommendation API — FastAPI, managed with uv.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    HF_HOME=/opt/huggingface \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false \
    PATH="/app/.venv/bin:${PATH}"

# Install third-party dependencies in a cacheable layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the application itself as a non-editable package.
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p "${HF_HOME}" \
    && chown -R appuser:appuser "${HF_HOME}"

# Bake the model into the image as the same non-root user used at runtime.
USER appuser
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

# Runtime inference must use the baked cache without remote metadata requests.
ENV HF_HUB_OFFLINE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import json; from urllib.request import urlopen; assert json.load(urlopen('http://127.0.0.1:8000/health', timeout=3))['status'] == 'ok'"

CMD ["uvicorn", "au_connect_recommendation_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
