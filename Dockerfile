# 1. Imagem base do Python
FROM python:3.13-slim

# 2. Instala dependências de sistema necessárias
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 3. Define a pasta de trabalho dentro do contêiner
WORKDIR /app

# 4. Instala o gerenciador de pacotes 'uv'
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 5. Copia os arquivos de configuração de dependências primeiro
# (Isso ajuda o Docker a usar o cache e ser mais rápido nos próximos builds)
COPY pyproject.toml uv.lock ./

# 6. Instala as bibliotecas do Python descritas no pyproject.toml
RUN uv pip install --system -r pyproject.toml

# 7. Instala os navegadores e dependências de sistema do Playwright
RUN playwright install --with-deps chromium

# 8. Copia o resto do código da sua máquina para dentro do contêiner
COPY . .

# 9. O comando padrão para rodar a sua aplicação
CMD ["python", "main.py"]
