# 1. Imagem base do Python
FROM python:3.13-slim

# 2. Variáveis de ambiente — logs em tempo real e encoding correto
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

# 3. Instala o uv directamente via pip (sem curl)
RUN pip install --no-cache-dir uv

# 4. Define a pasta de trabalho dentro do contêiner
WORKDIR /app

# 5. Copia os ficheiros de lock primeiro (cache de dependências)
COPY pyproject.toml uv.lock ./

# 6. Instala as dependências exactas do lockfile (reprodutível)
RUN uv sync --frozen --no-dev

# 7. Instala o Chromium e as dependências de sistema do Playwright
RUN uv run playwright install --with-deps chromium

# 8. Copia o resto do código
COPY . .

# 9. Comando padrão
CMD ["uv", "run", "python", "main.py"]
