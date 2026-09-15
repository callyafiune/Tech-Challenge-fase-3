FROM python:3.11.16-slim-bookworm AS base

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# O construtor do wheel nunca é herdado pelas imagens operacionais.
FROM base AS builder
COPY requirements-build.lock /tmp/requirements-build.lock
RUN pip install --no-cache-dir --no-compile -r /tmp/requirements-build.lock
COPY pyproject.toml ./
COPY src ./src
RUN pip wheel --no-deps --no-build-isolation --wheel-dir /dist .

# O pip da imagem Python instala em um venv sem duplicar pip/setuptools nele.
FROM base AS dependencias_runtime
RUN python -m venv --without-pip /opt/venv
COPY requirements-runtime.lock /tmp/requirements-runtime.lock
RUN python -m pip --python /opt/venv/bin/python install --no-cache-dir --no-compile \
    -r /tmp/requirements-runtime.lock
RUN --mount=type=bind,from=builder,source=/dist,target=/tmp/pacote \
    python -m pip --python /opt/venv/bin/python install --no-deps --no-compile /tmp/pacote/*.whl \
    && python -m pip --python /opt/venv/bin/python check

FROM dependencias_runtime AS dependencias_treinamento
# O estágio pai preserva /tmp/requirements-runtime.lock, incluído pelo lock de treinamento.
COPY requirements-treinamento.lock /tmp/requirements-treinamento.lock
RUN python -m pip --python /opt/venv/bin/python install --no-cache-dir --no-compile \
    -r /tmp/requirements-treinamento.lock \
    && python -m pip --python /opt/venv/bin/python check

FROM base AS operacao
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    MODEL_DIR=/app/models \
    MODEL_BACKEND=onnx

# Volumes novos recebem permissões compatíveis com a API e o treinamento.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home app \
    && mkdir -p /app/models /app/data \
    && chown app:app /app/models /app/data
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).close()"]
CMD ["uvicorn", "medical_classifier.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]

# Pipeline, Airflow e benchmark scikit-learn usam este perfil, sem ferramentas dev.
FROM operacao AS treinamento
COPY --from=dependencias_treinamento /opt/venv /opt/venv

# O último target é a imagem padrão: somente inferência ONNX e suas dependências.
FROM operacao AS runtime
COPY --from=dependencias_runtime /opt/venv /opt/venv
