-- ============================================================
-- BETS AFFILIATE TRACKER — Supabase Schema v3
-- ============================================================

create extension if not exists "pgcrypto";

-- ============================================================
-- 1. PLATAFORMAS
-- Representa o SOFTWARE de afiliados (Netrefer, MyAffiliates…)
-- NÃO guarda login_url aqui — cada operador tem o seu próprio domínio
-- O que é comum à plataforma: nome, slug, tem captcha ou não,
-- e o path de login (que é igual para todos os operadores Netrefer)
-- ============================================================
create table if not exists platforms (
    id              serial primary key,
    name            text not null unique,       -- "Netrefer"
    slug            text not null unique,       -- "netrefer"
    login_path      text not null default '',   -- "/affiliates/Account/Login"
                                                -- junta-se ao login_url da conta
    has_captcha     boolean not null default false,
    is_active       boolean not null default true,
    created_at      timestamptz not null default now()
);

-- ============================================================
-- 2. CONTAS
-- Uma linha por combinação Operador + Username
-- login_url aqui — é específico de cada operador
-- ============================================================
create table if not exists accounts (
    id              serial primary key,
    platform_id     int not null references platforms(id),

    -- Identificação do operador (do Excel: Operador + Empresa)
    operador        text not null,              -- "BetMGM", "Stake", "BetFair"…
    empresa         text,                       -- "Brasil", "Affiliabet", "Afiliagambling"…

    -- Credenciais de acesso
    username        text not null,
    login_url       text not null,              -- URL completo e único por operador
    file_name       text,                       -- prefixo do CSV: "BetMGM_TipsterpageBR"

    -- Estado
    is_active       boolean not null default true,
    status          text check (status in (
                        'idle','running','success','error','rate_limit','disabled'
                    )) default 'idle',
    last_login_at   timestamptz,
    last_success_at timestamptz,
    last_error_at   timestamptz,
    last_error_msg  text,
    retry_count     int not null default 0,

    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),

    unique(platform_id, operador, username)
);

-- ============================================================
-- 3. EXECUÇÕES
-- ============================================================
create table if not exists scrape_runs (
    id              bigserial primary key,
    account_id      int not null references accounts(id),
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    status          text check (status in ('running','success','error','skipped')),
    rows_imported   int,
    error_msg       text,
    duration_secs   int generated always as (
                        extract(epoch from (finished_at - started_at))::int
                    ) stored
);

-- ============================================================
-- 4. AFFILIATE_STATS — estrutura real do CSV Netrefer
--
-- Valores monetários chegam como strings com prefixo variável:
--   "R$20.00"        → BRL
--   "€-6.55"         → EUR
--   "£12.95"         → GBP
--   "$146.00"        → USD  (símbolo ambíguo — resolvido pela conta)
--   "COP174721.58"   → COP
--   "MXN 0.00"       → MXN
--   "PEN 117.00"     → PEN
--   "ARS 110,809.86" → ARS  (vírgula como separador de milhar)
--   "CLP 0.00"       → CLP
--
-- A moeda é guardada por linha (pode mudar entre marketing sources
-- dentro da mesma conta se o operador tiver multi-moeda)
-- ============================================================
create table if not exists affiliate_stats (
    id              bigserial primary key,
    account_id      int not null references accounts(id),
    platform_id     int not null references platforms(id),
    scrape_run_id   bigint references scrape_runs(id),

    -- Dimensão temporal (null nos registos mensais — usa-se report_month)
    report_date     date,

    -- Dimensão de marketing source
    marketing_source_id     int,
    marketing_source_name   text,

    -- Métricas de impressão
    views               int,
    unique_views        int,

    -- Métricas de clique
    clicks              int,
    unique_clicks       int,
    ctr                 numeric(8,6),   -- ex: 0.00% → 0.000000

    -- Métricas de conversão
    signups                         int,
    depositing_customers            int,
    active_customers                int,
    new_depositing_customers        int,
    new_active_customers            int,
    first_time_depositing_customers int,
    first_time_active_customers     int,

    -- Métricas financeiras (valor numérico limpo, sem símbolo)
    deposits        numeric(14,2),
    turnover        numeric(14,2),
    net_revenue     numeric(14,2),      -- pode ser negativo

    -- Moeda ISO 4217 detectada do prefixo do valor
    currency        char(3) not null,   -- BRL | EUR | GBP | USD | COP | MXN | PEN | ARS | CLP

    imported_at     timestamptz not null default now(),
    platform_name    text,
    operador         text,
    account_username text,

    -- Unicidade: conta + data + marketing source (diário)
    constraint uq_stat unique (account_id, report_date, marketing_source_id)
);

-- 1. Adiciona colunas necessárias para o relatório mensal
alter table affiliate_stats
    -- Período mensal (ex: 2026-06-01 = Junho 2026, sempre dia 1)
    add column if not exists report_month  date,
    -- Nova coluna CPA Triggered presente no CSV mensal
    add column if not exists cpa_triggered int;

-- report_date pode ser NULL nos registos mensais (usa-se report_month em vez disso)
alter table affiliate_stats
    alter column report_date drop not null;

-- 2. A constraint uq_stat existente usa report_date + marketing_source_id
--    Para o relatório mensal usamos report_month em vez de report_date
--    Criamos uma constraint separada para evitar conflitos
alter table affiliate_stats
    drop constraint if exists uq_stat_monthly;

alter table affiliate_stats
    add constraint uq_stat_monthly
    unique (account_id, report_month, marketing_source_id);

-- ============================================================
-- 5. ÍNDICES
-- ============================================================
create index if not exists idx_stats_date        on affiliate_stats(report_date desc);
create index if not exists idx_stats_account     on affiliate_stats(account_id);
create index if not exists idx_stats_platform    on affiliate_stats(platform_id);
create index if not exists idx_stats_run         on affiliate_stats(scrape_run_id);
create index if not exists idx_stats_currency    on affiliate_stats(currency);
create index if not exists idx_stats_source      on affiliate_stats(marketing_source_id);
create index if not exists idx_runs_account      on scrape_runs(account_id, started_at desc);
create index if not exists idx_accounts_platform on accounts(platform_id, is_active);
create index if not exists idx_accounts_operador on accounts(operador);
create index if not exists idx_stats_operador  on affiliate_stats(operador);
create index if not exists idx_stats_username  on affiliate_stats(account_username);

-- ============================================================
-- 6. TRIGGER: updated_at em accounts
-- ============================================================
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_accounts_updated_at on accounts;
create trigger trg_accounts_updated_at
    before update on accounts
    for each row execute function set_updated_at();

-- ============================================================
-- 7. RPC: incremento atómico do retry_count
-- ============================================================
create or replace function increment_retry(account_id int)
returns void language sql as $$
    update accounts
    set retry_count = retry_count + 1
    where id = account_id;
$$;

-- ============================================================
-- 8. VIEW: resumo diário por operador e marketing source
-- ============================================================
create or replace view v_daily_summary as
select
    p.name                                  as platform,
    a.operador,
    a.empresa,
    s.currency,
    s.report_date,
    s.marketing_source_name                 as source,
    sum(s.views)                            as views,
    sum(s.clicks)                           as clicks,
    sum(s.signups)                          as signups,
    sum(s.first_time_depositing_customers)  as ftds,
    sum(s.depositing_customers)             as depositing_customers,
    sum(s.active_customers)                 as active_customers,
    sum(s.deposits)                         as deposits,
    sum(s.net_revenue)                      as net_revenue
from affiliate_stats s
join accounts  a on a.id = s.account_id
join platforms p on p.id = s.platform_id
group by p.name, a.operador, a.empresa, s.currency, s.report_date, s.marketing_source_name
order by s.report_date desc, a.operador;

create or replace view v_daily_summary as
select
    s.platform_name,
    s.operador,
    s.account_username,
    s.currency,
    s.report_date,
    s.report_month,
    s.marketing_source_name                 as source,
    sum(s.views)                            as views,
    sum(s.clicks)                           as clicks,
    sum(s.signups)                          as signups,
    sum(s.first_time_depositing_customers)  as ftds,
    sum(s.cpa_triggered)                    as cpa_triggered,
    sum(s.depositing_customers)             as depositing_customers,
    sum(s.active_customers)                 as active_customers,
    sum(s.deposits)                         as deposits,
    sum(s.net_revenue)                      as net_revenue
from affiliate_stats s
group by
    s.platform_name, s.operador, s.account_username,
    s.currency, s.report_date, s.report_month, s.marketing_source_name
order by coalesce(s.report_date, s.report_month) desc, s.operador;

-- 3. Índice no report_month
create index if not exists idx_stats_month on affiliate_stats(report_month desc);

-- ============================================================
-- 9. SEED: Netrefer
-- login_path é o sufixo comum a todos os operadores Netrefer
-- ============================================================
insert into platforms (name, slug, login_path, has_captcha) values
    ('Netrefer', 'netrefer', '/affiliates/Account/Login', false)
on conflict (slug) do nothing;
