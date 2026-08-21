-- Apuração PIS/COFINS — migração 002 (14/08/2026): apuração passa a ser por GRUPO (CNPJ raiz — matriz +
-- filiais consolidadas), não mais por uma única empresa/filial isolada; e a fonte primária do cálculo passa
-- a ser a Rotina 1024 (Livro RAICMS), não mais o Relatório 1096 direto. Ver metodologia atualizada no
-- projeto Claude "PIS/COFINS" (claude/metodologia-pis-cofins-lucro-real.md) para o porquê completo.
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase, depois do 001_schema.sql já aplicado. É seguro rodar
-- de novo (idempotente) — usa "if not exists"/checagens antes de alterar o que já existir.

-- ============================================================================================
-- 1) COMPETENCIAS: chave passa de (empresa_id, ano, mes, modulo) para (cnpj_raiz, ano, mes, modulo).
--    empresa_id fica NULLABLE e continua na tabela só como referência histórica (aponta pra qual empresa
--    era usada como representante do grupo antes desta migração) — não é mais usado para nada novo.
-- ============================================================================================
alter table competencias add column if not exists cnpj_raiz text;

update competencias c
set cnpj_raiz = e.cnpj_raiz
from empresas e
where e.id = c.empresa_id and c.cnpj_raiz is null;

alter table competencias alter column empresa_id drop not null;
alter table competencias alter column cnpj_raiz set not null;

do $$
begin
    if exists (
        select 1 from pg_constraint
        where conname = 'competencias_empresa_id_ano_mes_modulo_key'
    ) then
        alter table competencias drop constraint competencias_empresa_id_ano_mes_modulo_key;
    end if;
end $$;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'competencias_cnpj_raiz_ano_mes_modulo_key'
    ) then
        alter table competencias
            add constraint competencias_cnpj_raiz_ano_mes_modulo_key unique (cnpj_raiz, ano, mes, modulo);
    end if;
end $$;

create index if not exists ix_competencias_cnpj_raiz on competencias(cnpj_raiz);

-- ============================================================================================
-- 2) RELATORIO_PC_ITENS (1096): ganha empresa_id (qual filial gerou aquele item) — antes disso, a
--    competência já era 1:1 com uma única empresa, então cada item "pertencia" à empresa da própria
--    competência; com múltiplas filiais numa mesma competência (grupo), cada item precisa dizer de qual
--    filial veio. Backfill a partir do empresa_id que a competência tinha ANTES desta migração (dado real
--    já importado, ex.: Sodine Matriz jul/2026), para não perder a rastreabilidade do que já está no banco.
-- ============================================================================================
alter table relatorio_pc_itens add column if not exists empresa_id bigint references empresas(id);

update relatorio_pc_itens ri
set empresa_id = c.empresa_id
from competencias c
where c.id = ri.competencia_id and ri.empresa_id is null and c.empresa_id is not null;

create index if not exists ix_rpc_itens_empresa on relatorio_pc_itens(empresa_id);

-- ============================================================================================
-- 3) RESUMO_1024_PC: dado agregado por CFOP extraído do PDF da Rotina 1024 (Livro RAICMS Modelo P9),
--    UM POR FILIAL — é isso que vira a base do cálculo (valor_contabil - valor_icms) por grupo de CFOP,
--    somado entre todas as filiais da mesma competência (grupo). tipo_operacao é derivado do próprio CFOP
--    (1xxx-3xxx = entrada, 5xxx-7xxx = saída) no momento da importação, não vem do PDF diretamente.
-- ============================================================================================
create table if not exists resumo_1024_pc (
    id                bigserial primary key,
    competencia_id    bigint not null references competencias(id) on delete cascade,
    empresa_id        bigint not null references empresas(id),
    tipo_operacao     text not null check (tipo_operacao in ('entrada','saida')),
    cfop              integer not null,
    valor_contabil    numeric(14,2) not null default 0,
    valor_base_icms   numeric(14,2) not null default 0,
    valor_icms        numeric(14,2) not null default 0,
    importado_em      timestamptz not null default now(),
    unique (competencia_id, empresa_id, cfop)
);
create index if not exists ix_resumo1024pc_competencia on resumo_1024_pc(competencia_id);
create index if not exists ix_resumo1024pc_empresa on resumo_1024_pc(empresa_id);
create index if not exists ix_resumo1024pc_cfop on resumo_1024_pc(cfop);

alter table resumo_1024_pc enable row level security;
drop policy if exists "authenticated_full_access" on resumo_1024_pc;
create policy "authenticated_full_access" on resumo_1024_pc for all to authenticated using (true) with check (true);

-- ============================================================================================
-- 4) INCONSISTENCIAS_PC: o tipo 'cfop_sem_grupo' agora também pode vir do 1024 (fonte primária), não só
--    do 1096 — adiciona colunas pra saber de qual fonte e de qual FILIAL veio o achado (sem isso, reimportar
--    o 1096 de uma filial apagaria/recriaria as inconsistências de outra filial da mesma competência).
-- ============================================================================================
alter table inconsistencias_pc add column if not exists fonte text;
comment on column inconsistencias_pc.fonte is
    'De onde veio o achado: rotina_1024 (fonte primária do cálculo) ou relatorio_1096 (conferência/CST). '
    'Nulo em registros antigos, criados antes desta coluna existir.';

alter table inconsistencias_pc add column if not exists empresa_id bigint references empresas(id);
comment on column inconsistencias_pc.empresa_id is
    'Qual filial gerou o achado — necessário desde que uma competência passou a abranger várias filiais '
    '(grupo). Nulo em registros antigos.';
