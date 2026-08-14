-- Apuração PIS/COFINS — módulo Lucro Real (não-cumulativo), schema inicial (14/08/2026)
-- Mesma arquitetura do projeto "Apuração ICMS": Postgres via Supabase (conexão direta, não PostgREST),
-- autenticação via Supabase Auth, todos os usuários autenticados com o mesmo nível de acesso.
-- Metodologia completa (mapeamento do relatório 1096, listas de CFOP por linha, tabela CST, fórmula da
-- apuração) documentada no projeto Claude "PIS/COFINS" (claude/metodologia-pis-cofins-lucro-real.md) —
-- leia antes de mexer neste schema ou no motor de cálculo.

-- ============================================================================================
-- EMPRESAS (cadastro do grupo econômico — mesmo cadastro usado no módulo ICMS; o campo `regime`
-- decide qual módulo de PIS/COFINS se aplica a cada empresa: só "Lucro Real*" usa este módulo)
-- ============================================================================================
create table if not exists empresas (
    id                bigserial primary key,
    filial_winthor    text,
    razao_social      text not null,
    cnpj              text not null unique,
    cnpj_raiz         text generated always as (
                          left(regexp_replace(cnpj, '[^0-9]', '', 'g'), 8)
                      ) stored,
    inscricao_estadual text,
    inscricao_municipal text,
    uf                text,
    regime            text,
    is_empresa_apurada boolean not null default false,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

-- ============================================================================================
-- CFOP × PIS/COFINS (classifica cada CFOP na linha da apuração em que ele entra — 1.1/1.2/1.4/1.6 no
-- débito, 5.1/5.5/5.7/5.8 no crédito — conforme a planilha em uso pelo usuário, ver metodologia no
-- projeto). Ajuste manual (`grupo_ajuste`) sobrepõe o padrão, mesmo padrão do `cfop.is_st_ajuste` do ICMS.
-- ============================================================================================
create table if not exists cfop_pis_cofins (
    codigo            integer primary key,
    descricao         text,
    direcao           text not null check (direcao in ('entrada','saida')),
    grupo_padrao      text not null,   -- '1.1','1.2','1.4','1.6' (saída) | '5.1','5.5','5.7','5.8' (entrada)
    grupo_ajuste      text,            -- override manual — null = usa grupo_padrao
    observacao        text,
    updated_at        timestamptz not null default now()
);
comment on column cfop_pis_cofins.grupo_ajuste is
    'Override manual do grupo_padrao — para CFOPs que a empresa trata diferente do padrão do grupo, sem '
    'precisar mudar código (mesmo padrão do cfop.is_st_ajuste no módulo ICMS).';

create or replace view cfop_pis_cofins_efetivo as
    select codigo, descricao, direcao, coalesce(grupo_ajuste, grupo_padrao) as grupo, observacao
    from cfop_pis_cofins;

-- ============================================================================================
-- CST de PIS/COFINS (tabela oficial da Receita Federal — define se a Entrada gera crédito e se a
-- Saída gera débito "cheio". CST fora da tabela = inconsistência pendente, não é ignorado.)
-- ============================================================================================
create table if not exists cst_pis_cofins (
    codigo                integer primary key,
    descricao             text not null,
    direcao               text not null check (direcao in ('entrada','saida')),
    gera_direito_credito  boolean,  -- só relevante para direcao='entrada'
    gera_debito           boolean,  -- só relevante para direcao='saida'
    ajuste_manual         boolean,  -- override manual (null = usa o padrão da coluna relevante)
    observacao            text,
    updated_at            timestamptz not null default now()
);

create or replace view cst_pis_cofins_efetivo as
    select codigo, descricao, direcao,
           case when direcao = 'entrada' then coalesce(ajuste_manual, gera_direito_credito) end
               as gera_direito_credito,
           case when direcao = 'saida' then coalesce(ajuste_manual, gera_debito) end as gera_debito,
           observacao
    from cst_pis_cofins;

-- ============================================================================================
-- COMPETENCIAS (períodos de apuração, um por empresa+ano+mês+módulo)
-- ============================================================================================
create table if not exists competencias (
    id            bigserial primary key,
    empresa_id    bigint not null references empresas(id),
    ano           integer not null,
    mes           integer not null check (mes between 1 and 12),
    modulo        text not null default 'pis_cofins_lucro_real'
                  check (modulo in ('pis_cofins_lucro_real','pis_cofins_lucro_presumido')),
    status        text not null default 'aberta'
                  check (status in ('aberta','importada','calculada','fechada')),
    created_at    timestamptz not null default now(),
    unique (empresa_id, ano, mes, modulo)
);

-- ============================================================================================
-- RELATORIO_PC_ITENS (dado bruto importado do Relatório 1096 — Entrada/Saída). Granularidade de item
-- agregado (produto × NCM × CST × CFOP), SEM número de NF — ver metodologia no projeto sobre por quê.
-- ============================================================================================
create table if not exists relatorio_pc_itens (
    id                  bigserial primary key,
    competencia_id      bigint not null references competencias(id) on delete cascade,
    tipo_operacao       text not null check (tipo_operacao in ('entrada','saida')),
    produto_codigo      text,
    ncm                 text,
    cst                 integer not null,
    cfop                integer not null,
    quantidade          numeric(14,3),
    valor_contabil      numeric(14,2),
    valor_desconto      numeric(14,2),
    valor_itens         numeric(14,2),
    valor_tributado     numeric(14,2),
    aliq_pis            numeric(9,4),
    valor_pis           numeric(14,2),
    aliq_cofins         numeric(9,4),
    valor_cofins        numeric(14,2),
    valor_nao_tributado numeric(14,2),
    importado_em        timestamptz not null default now()
);
create index if not exists ix_rpc_itens_competencia on relatorio_pc_itens(competencia_id);
create index if not exists ix_rpc_itens_cfop on relatorio_pc_itens(cfop);
create index if not exists ix_rpc_itens_cst on relatorio_pc_itens(cst);
create index if not exists ix_rpc_itens_tipo on relatorio_pc_itens(tipo_operacao);

-- ============================================================================================
-- LANÇAMENTOS MANUAIS — nesta versão, só Aluguéis (Prédios/Máquinas) e Depreciação (pedido do usuário
-- em 14/08/2026: "só Aluguéis e Depreciação por enquanto"). Gera crédito de PIS 1,65% / COFINS 7,60%
-- sobre a base informada. Extensível: adicionar um novo `tipo` no check constraint quando o próximo
-- tipo de lançamento manual (energia elétrica, fretes Supply Log, receitas financeiras...) for pedido.
-- ============================================================================================
create table if not exists lancamentos_manuais_pc (
    id                bigserial primary key,
    competencia_id    bigint not null references competencias(id) on delete cascade,
    tipo              text not null check (tipo in (
                          'aluguel_predio_credito', 'aluguel_maquinas_credito', 'depreciacao_credito'
                      )),
    descricao         text not null,
    base_valor        numeric(14,2) not null,  -- valor informado (ex: valor do aluguel/depreciação do mês)
    valor_pis         numeric(14,2) not null,  -- base_valor × 1,65%
    valor_cofins      numeric(14,2) not null,  -- base_valor × 7,60%
    criado_por        uuid references auth.users(id),
    created_at        timestamptz not null default now()
);
create index if not exists ix_lmpc_competencia on lancamentos_manuais_pc(competencia_id);

-- ============================================================================================
-- APURACAO_PC_LINHAS (resultado calculado — espelha as linhas 1.x a 11.x da planilha em uso)
-- ============================================================================================
create table if not exists apuracao_pc_linhas (
    id                bigserial primary key,
    competencia_id    bigint not null references competencias(id) on delete cascade,
    linha             text not null,  -- '1.1', '1.2', ... '11.3'
    descricao         text not null,
    valor_pis         numeric(14,2) not null default 0,
    valor_cofins      numeric(14,2) not null default 0,
    manual            boolean not null default false,  -- true = linha não calculada automaticamente (pendente)
    detalhe           jsonb,
    calculado_em      timestamptz not null default now(),
    unique (competencia_id, linha)
);

-- ============================================================================================
-- SALDO CREDOR ANTERIOR (entrada manual das linhas 8.1/8.2 — enquanto não há encadeamento automático
-- entre competências, mesmo ponto em aberto do "linha 09" do módulo ICMS)
-- ============================================================================================
create table if not exists saldo_credor_anterior_pc (
    id                bigserial primary key,
    competencia_id    bigint not null references competencias(id) on delete cascade unique,
    saldo_pis         numeric(14,2) not null default 0,
    saldo_cofins      numeric(14,2) not null default 0,
    updated_at        timestamptz not null default now()
);

-- ============================================================================================
-- INCONSISTENCIAS (CST fora da tabela oficial, CFOP sem grupo cadastrado — sinalizado, não ignorado)
-- ============================================================================================
create table if not exists inconsistencias_pc (
    id                bigserial primary key,
    competencia_id    bigint not null references competencias(id) on delete cascade,
    tipo              text not null check (tipo in ('cst_nao_mapeado','cfop_sem_grupo')),
    cst               integer,
    cfop              integer,
    tipo_operacao     text,
    descricao         text not null,
    status            text not null default 'pendente' check (status in ('pendente','revisado','ignorado')),
    revisado_por      uuid references auth.users(id),
    revisado_em       timestamptz,
    created_at        timestamptz not null default now()
);
create index if not exists ix_inconsistencias_pc_competencia on inconsistencias_pc(competencia_id);
create index if not exists ix_inconsistencias_pc_status on inconsistencias_pc(status);

-- ============================================================================================
-- RLS — todos os usuários autenticados têm o mesmo nível de acesso (mesma decisão do módulo ICMS)
-- ============================================================================================
alter table empresas enable row level security;
alter table cfop_pis_cofins enable row level security;
alter table cst_pis_cofins enable row level security;
alter table competencias enable row level security;
alter table relatorio_pc_itens enable row level security;
alter table lancamentos_manuais_pc enable row level security;
alter table apuracao_pc_linhas enable row level security;
alter table saldo_credor_anterior_pc enable row level security;
alter table inconsistencias_pc enable row level security;

do $$
declare
    t text;
begin
    for t in select unnest(array[
        'empresas','cfop_pis_cofins','cst_pis_cofins','competencias','relatorio_pc_itens',
        'lancamentos_manuais_pc','apuracao_pc_linhas','saldo_credor_anterior_pc','inconsistencias_pc'
    ])
    loop
        execute format('drop policy if exists "authenticated_full_access" on %I', t);
        execute format(
            'create policy "authenticated_full_access" on %I '
            'for all to authenticated using (true) with check (true)', t
        );
    end loop;
end $$;
