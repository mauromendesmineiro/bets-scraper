# Bets Affiliate Scraper

Scraper automatizado de relatórios de afiliados — suporta múltiplas contas e plataformas.

## Estrutura do projeto

```
bets2/
├── src/
│   ├── scraper/
│   │   ├── login.py        # handlers de login por plataforma (Netrefer, Income Access, MyAffiliates, Affilka)
│   │   ├── status.py       # detecção de status pós-login (multi-idioma: PT, ES, IT, EN)
│   │   └── captcha.py      # resolução de captcha via 2captcha
│   ├── storage/
│   │   ├── db.py           # cliente Supabase (contas, runs, upsert de stats)
│   │   └── csv_parser.py   # parser de CSV Netrefer (diário e mensal, multi-moeda)
│   ├── utils/
│   │   ├── logger.py       # logging estruturado
│   │   └── notify.py       # relatório de erros por email (SMTP/Gmail)
│   └── config.py           # variáveis de ambiente centralizadas
├── sql/
│   ├── 001_schema.sql      # schema completo do Supabase
│   └── queries.sql         # queries utilitárias
├── tools/
│   └── migrate_from_excel.py  # migração única do Excel → Supabase
├── main.py                 # orquestrador principal
├── .env.example            # template de variáveis de ambiente
└── pyproject.toml
```

## Plataformas suportadas

| Slug | Plataforma | Captcha |
|---|---|---|
| `netrefer` | Netrefer | Não |
| `income_access` | Income Access | Sim (2captcha) |
| `myaffiliates` | MyAffiliates | Não |
| `affilka` | Affilka | Não |

## Fluxo por conta

1. Busca contas ativas no Supabase
2. Abre browser Playwright (headless)
3. Login com handler da plataforma (com ou sem captcha)
4. Navega para `MarketingSourceMonthlyFigures`
5. Seleciona o mês atual e faz download do CSV
6. Parse do CSV → schema unificado
7. Upsert no Supabase (`affiliate_stats`)
8. Atualiza status da conta

## Setup local (passo a passo)

### 1. Supabase

1. Cria projeto em [supabase.com](https://supabase.com)
2. Vai a **SQL Editor** e executa o conteúdo de `sql/001_schema.sql`
3. Copia o **Project URL** e a **anon key** (Settings → API)

### 2. Variáveis de ambiente

```bash
cp .env.example .env
# Edita .env com os teus valores reais
```

> [!WARNING]
> Ao preencher o `.env`, certifique-se de que **não há espaços em branco** no final das linhas (ex: `HEADLESS=true    `). Coloque comentários sempre em linhas separadas.

Variáveis obrigatórias:

| Variável | Descrição |
|---|---|
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_KEY` | Anon key do Supabase |
| `PASS_<SLUG>_<OPERADOR>_<USERNAME>` | Senha de cada conta (ver abaixo) |

Variáveis opcionais:

| Variável | Padrão | Descrição |
|---|---|---|
| `HEADLESS` | `true` | Modo headless do browser |
| `SLOW_MO` | `0` | Delay entre ações do Playwright (ms) |
| `DEFAULT_TIMEOUT` | `15000` | Timeout padrão do Playwright (ms) |
| `RATE_LIMIT_WAIT` | `65` | Espera em segundos ao encontrar rate limit |
| `SLEEP_BETWEEN` | `3` | Pausa entre contas (segundos) |
| `DATA_DIR` | `data` | Pasta para CSVs baixados |
| `LOGS_DIR` | `logs` | Pasta de logs |
| `TWOCAPTCHA_API_KEY` | — | Chave 2captcha (obrigatório para plataformas com captcha) |
| `SMTP_USER` | — | Email remetente (Gmail) para relatório de erros |
| `SMTP_PASSWORD` | — | Senha de app Gmail |
| `NOTIFY_TO` | — | Email(s) destinatário(s), separados por vírgula |
| `NOTIFY_CC` | — | Email(s) em cópia |
| `NOTIFY_BCC` | — | Email(s) em cópia oculta |

**Formato das senhas:**

```
PASS_<SLUG>_<OPERADOR>_<USERNAME>=minhasenha
```

Exemplo: conta `user@email.com`, operador `CasinoXYZ`, plataforma `netrefer`:
```
PASS_NETREFER_CASINOXYZ_USER_EMAIL_COM=minhasenha
```

### 3. Instalar dependências

```bash
# Usando uv (recomendado)
uv sync

# Ou pip
pip install -e ".[dev]"

# Instalar browsers do Playwright
playwright install chromium
```

### 4. Migrar contas do Excel

```bash
python tools/migrate_from_excel.py --excel config/logins.xlsx
```

### 5. Executar localmente

```bash
# Todas as contas
python main.py

# Só uma plataforma
python main.py --platform netrefer

# Contas específicas por ID
python main.py --accounts 25 31 42

# Sem escrever no DB (teste)
python main.py --dry-run

# Combinações
python main.py --platform netrefer --dry-run
python main.py --accounts 25 --dry-run
```

## Adicionar nova plataforma

1. `sql/001_schema.sql`: adiciona `INSERT INTO platforms` com o novo slug
2. `src/scraper/login.py`: cria `NovaPlataformaLoginHandler` e registra em `HANDLERS`
3. `src/storage/csv_parser.py`: ajusta `COLUMN_ALIASES` se necessário
4. `.env`: adiciona as senhas das novas contas

Exemplo de handler mínimo:

```python
class MinhaPlataformaLoginHandler(BaseLoginHandler):
    SEL_USERNAME = "input[name='user']"
    SEL_PASSWORD = "input[name='pass']"
    SEL_SUBMIT   = "button#login"
    SEL_AGREE    = None
```

Para plataformas com captcha:

```python
class MinhaPlataformaLoginHandler(BaseLoginHandler):
    SEL_USERNAME      = "input[name='user']"
    SEL_PASSWORD      = "input[name='pass']"
    SEL_SUBMIT        = "button#login"
    SEL_CAPTCHA       = "img.captcha"
    SEL_CAPTCHA_INPUT = "input[name='code']"
    HAS_CAPTCHA       = True
```

## Deploy e Produção (GitHub Actions)

O scraper é executado automaticamente via GitHub Actions todos os dias às **07:00 UTC** (`.github/workflows/scraper.yml`).

### Configurar secrets no GitHub

1. Vai a **Settings → Secrets and variables → Actions** no repositório
2. Adiciona cada variável do `.env` como um secret (`SUPABASE_URL`, `SUPABASE_KEY`, `PASS_...`, etc.)

### Executar manualmente

No GitHub, vai a **Actions → Daily Bets Scraper → Run workflow**.

## Notificações de erro

Ao final de cada execução, se houver contas com erro, um email HTML é enviado via SMTP (Gmail) com:
- ID, plataforma, operador, username e mensagem de erro de cada conta
- Comando pronto para reprocessar apenas as contas com falha

Requer `SMTP_USER`, `SMTP_PASSWORD` e `NOTIFY_TO` definidos no `.env`.
