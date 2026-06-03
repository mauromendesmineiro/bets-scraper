# Bets Affiliate Scraper

Scraper automatizado de relatórios de afiliados — 89 contas, 4 plataformas.

## Estrutura do projecto

```
bets/
├── src/
│   ├── scraper/
│   │   ├── login.py        # handlers de login por plataforma
│   │   ├── status.py       # detecção de status pós-login
│   │   └── captcha.py      # resolução de captcha via 2captcha
│   ├── storage/
│   │   ├── db.py           # cliente Supabase
│   │   └── csv_parser.py   # normalização dos CSVs das 4 plataformas
│   ├── utils/
│   │   └── logger.py       # logging estruturado
│   └── config.py           # variáveis de ambiente centralizadas
├── sql/
│   └── 001_schema.sql      # schema completo do Supabase
├── tools/
│   └── migrate_from_excel.py  # migração única do Excel → Supabase
├── main.py                 # orquestrador principal
├── .env.example            # template de variáveis de ambiente
└── pyproject.toml
```

## Setup local (passo a passo)

### 1. Supabase

1. Cria projecto em [supabase.com](https://supabase.com)
2. Vai a **SQL Editor** e corre o conteúdo de `sql/001_schema.sql`
3. Copia o **Project URL** e a **anon key** (Settings → API)

### 2. Variáveis de ambiente

```bash
cp .env.example .env
# Edita .env com os teus valores reais
```
> [!WARNING]
> Ao preencher o seu arquivo `.env`, certifique-se de que **não há espaços em branco** no final das linhas (ex: `HEADLESS=true    `). O Docker lê esses espaços e isso pode causar erros. Coloque comentários sempre em linhas separadas.

### 3. Instalar dependências

```bash
# Usando uv (recomendado — já tens no projecto)
uv sync

# Ou pip
pip install -e ".[dev]"

# Instalar browsers do Playwright
playwright install chromium
```

### 4. Migrar contas do Excel
# Corre a migração
python tools/migrate_from_excel.py \
    --excel config/logins.xlsx \

# 1. Revisa tools/migrate_accounts.sql
# 2. Corre o SQL no Supabase SQL Editor
# 3. Adiciona .env.passwords ao .env
```

### 5. Ajustar mapeamentos de CSV

Abre `src/storage/csv_parser.py` e verifica os `ColumnMap` de cada plataforma.
Os nomes das colunas têm de corresponder exactamente ao que está nos CSVs reais.

Para verificar:
```bash
python -c "
import pandas as pd
df = pd.read_csv('data/algum_ficheiro.csv')
print(df.columns.tolist())
print(df.head(2))
"
```

### 6. Correr localmente

```bash
# Teste sem escrever no DB
python main.py --dry-run

# Só uma plataforma
python main.py --platform netrefer

# Todas as plataformas
python main.py
```

## Ajustar selectores por plataforma

Se uma plataforma tiver selectores diferentes, edita o handler em `src/scraper/login.py`:

```python
class MinhaPlataformaLoginHandler(BaseLoginHandler):
    SEL_USERNAME = "input[name='user']"   # selector real
    SEL_PASSWORD = "input[name='pass']"
    SEL_SUBMIT   = "button#login"
```

Para plataformas com captcha, define também:
```python
    HAS_CAPTCHA       = True
    SEL_CAPTCHA       = "img.captcha"         # selector da imagem
    SEL_CAPTCHA_INPUT = "input[name='code']"  # onde escrever a solução
```

## Adicionar nova plataforma

1. `sql/`: adiciona `INSERT INTO platforms` com o novo slug
2. `login.py`: cria `NovaPlataformaLoginHandler` e regista em `HANDLERS`
3. `csv_parser.py`: cria `ColumnMap` com as colunas do CSV e regista em `PLATFORM_MAPS`
4. `.env`: adiciona as passwords das novas contas

## Deploy e Produção (Railway + Docker)

O projeto já está configurado com um `Dockerfile` pronto para produção.

### 1. Rodando com Docker Localmente

Para testar o robô isolado na sua máquina usando o Docker:

```bash
# 1. Construir a imagem (apenas quando alterar código Python)
docker build -t bets-scraper .

# 2. Executar o robô (mapeando a pasta data e lendo o .env)
docker run -it --rm --env-file .env -v "${PWD}/data:/app/data" bets-scraper

# 3. Executar o robô com argumentos específicos
docker run -it --rm --env-file .env -v "${PWD}/data:/app/data" bets-scraper python main.py --accounts 25
```

### 2. Publicando no Railway

1. Adicione as alterações ao GitHub e faça o push (`git push origin main`).
2. Crie um novo projeto no [Railway.app](https://railway.app) e escolha **Deploy from GitHub repo**.
3. Selecione o repositório deste projeto.
4. Vá até a aba **Variables** no painel do Railway e cole todas as variáveis e valores do seu arquivo `.env` local.
5. Certifique-se de que a variável `HEADLESS` está configurada como `true` nas variáveis do Railway.
6. O Railway fará o build do Dockerfile automaticamente e iniciará o scraper. Acompanhe pela aba **View Logs**.
