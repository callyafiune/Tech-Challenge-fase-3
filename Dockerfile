FROM python:3.11.16-slim-bookworm AS dependencias

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
RUN python -m venv /opt/venv
COPY requirements.lock ./
RUN pip install -r requirements.lock

# Alterações no código invalidam apenas a construção e a instalação deste wheel.
FROM dependencias AS builder
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --no-deps --no-build-isolation --wheel-dir /dist .

FROM dependencias AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    MODEL_DIR=/app/models \
    MODEL_BACKEND=onnx

WORKDIR /app
# Os volumes novos herdam estas permissões, permitindo também treino sem root.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home app \
    && mkdir -p /app/models /app/data \
    && chown app:app /app/models /app/data
# O venv já vem do estágio estável; somente o pacote da aplicação ganha nova camada.
COPY --from=builder /dist /tmp/pacote
RUN pip install --no-cache-dir --no-index --no-deps --no-compile /tmp/pacote/*.whl \
    && rm -r /tmp/pacote

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).close()"]
CMD ["uvicorn", "medical_classifier.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
