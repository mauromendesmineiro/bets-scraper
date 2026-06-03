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

## Proximos passos: migração para cloud

Ver `docs/cloud-setup.md` (a criar quando estiveres pronto para migrar).
Opções recomendadas: Railway (simples) ou Google Cloud Run (escalável).
