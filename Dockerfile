# Imagem de produção do agente da Patas & Cia (bloco 11, ADR 0010).
# Segredos NUNCA entram na imagem: chegam como variáveis de ambiente da plataforma, na hora de rodar.
#
#   docker build -t patas-agente .
#   docker run -p 8000:8000 -v patas-dados:/data --env-file .env patas-agente

FROM python:3.12-slim

# uv fixo na mesma série usada no desenvolvimento: a instalação é reproduzível pelo uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependências primeiro, código depois: mudar o código não reinstala as bibliotecas (cache de camadas).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# Usuário sem privilégio: se alguém explorar o app, não vira dono do container.
RUN useradd --create-home --uid 10001 patas && mkdir /data && chown patas /data
USER patas

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PATAS_DB_PATH=/data/patas.db \
    HOST=0.0.0.0 \
    PORT=8000 \
    FORWARDED_ALLOW_IPS=*

# O banco mora no volume: sobrevive a novos deploys da imagem.
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/saude', timeout=4)"

CMD ["python", "-m", "patas.servidor"]
