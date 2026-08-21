-- Apuração PIS/COFINS — migração 005 (18/08/2026): agrupamento de inconsistências repetidas + "aprendizado"
-- (exceções que se replicam nas próximas apurações) para as regras de CST × CFOP/NCM do 1096 — mesma
-- estrutura já usada no módulo ICMS normal (ver sql/008_agrupar_inconsistencias.sql e
-- sql/009_excecoes_inconsistencia.sql daquele projeto), adaptada aqui: "um mesmo erro pode se repetir em
-- vários itens/CFOPs — é melhor agrupar numa linha só com quantidade, e se o analista já revisou e decidiu
-- que aquilo está certo, isso deve valer sozinho nas competências seguintes, sem pedir revisão de novo".
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase, depois do 001/002/003/004. Seguro de rodar de novo.

-- ============================================================================================
-- 1) Agrupamento — cada combinação (competencia_id, empresa_id, tipo, chave_agrupamento) vira UMA linha em
--    inconsistencias_pc, com quantidade = número de itens do Relatório 1096 por trás dela, em vez de uma
--    linha por CFOP/NCM/CST já feito hoje sem contagem.
-- ============================================================================================
alter table inconsistencias_pc
    add column if not exists chave_agrupamento text,
    add column if not exists quantidade integer not null default 1,
    add column if not exists justificativa text,
    add column if not exists aplicada_por_excecao boolean not null default false;

comment on column inconsistencias_pc.chave_agrupamento is
    'Chave de agrupamento dentro da mesma (competencia_id, empresa_id, tipo) — ex.: "cfop:1124|cst:50|'
    'op:entrada" para cst_regra_cfop, "ncm:22072019|cst:50|op:entrada" para cst_regra_ncm, "cst:98|'
    'op:entrada" para cst_regra_alerta. Usada também como chave de excecoes_inconsistencia_pc (ver abaixo).';
comment on column inconsistencias_pc.quantidade is
    'Quantos itens do Relatório 1096 (relatorio_pc_itens) geraram esta mesma inconsistência agrupada.';
comment on column inconsistencias_pc.justificativa is
    'Texto livre do analista explicando por que este grupo não é um erro de verdade, ou o que foi feito. '
    'Preenchido manualmente ao revisar, ou automaticamente quando aplicada_por_excecao=true (copiado de '
    'excecoes_inconsistencia_pc.justificativa).';
comment on column inconsistencias_pc.aplicada_por_excecao is
    'true quando esta inconsistência já nasceu resolvida (status=revisado + justificativa preenchida) '
    'porque bateu com uma regra em excecoes_inconsistencia_pc cadastrada numa competência anterior — não '
    'foi revisada manualmente desta vez.';

-- ============================================================================================
-- 2) "Aprendizado" — quando o analista marca uma inconsistência (grupo) como revisada com justificativa e
--    pede pra replicar, essa decisão vale sozinha nas competências seguintes desta mesma filial, sem
--    pedir revisão de novo do mesmo caso todo mês.
-- ============================================================================================
create table if not exists excecoes_inconsistencia_pc (
    id                bigserial primary key,
    empresa_id        bigint not null references empresas(id) on delete cascade,
    tipo              text not null check (tipo in ('cst_regra_cfop', 'cst_regra_ncm', 'cst_regra_alerta')),
    chave_agrupamento text not null,
    ncm               text,
    cfop              integer,
    tipo_operacao     text,
    justificativa     text not null,
    ativa             boolean not null default true,
    criado_por        uuid references auth.users(id),
    criado_por_email  text,
    created_at        timestamptz not null default now(),
    unique (empresa_id, tipo, chave_agrupamento)
);
create index if not exists ix_excecoes_pc_empresa on excecoes_inconsistencia_pc(empresa_id, tipo);
comment on table excecoes_inconsistencia_pc is
    'Regras "aprendidas" das checagens de CST × CFOP/NCM do 1096: quando o analista marca uma inconsistência '
    'agrupada como revisada com justificativa e pede pra replicar, entra aqui. Nas próximas importações do '
    '1096, cst_regras_pc.registrar_inconsistencias_cst_regras checa esta tabela ANTES de gravar — se a '
    'combinação (empresa, tipo, chave_agrupamento) tiver uma exceção ativa, a inconsistência ainda é '
    'registrada (fica no histórico/quantidade), mas já nasce com status=''revisado'' e a justificativa '
    'preenchida, sem aparecer como pendente de novo.';

alter table excecoes_inconsistencia_pc enable row level security;
drop policy if exists "authenticated_full_access" on excecoes_inconsistencia_pc;
create policy "authenticated_full_access" on excecoes_inconsistencia_pc
    for all to authenticated using (true) with check (true);

-- Não precisa de backfill manual: as inconsistências de CST × CFOP/NCM (tipo cst_regra_cfop/cst_regra_ncm/
-- cst_regra_alerta) já são apagadas e recriadas do zero a cada importação do 1096 (ver
-- cst_regras_pc.registrar_inconsistencias_cst_regras) — a próxima importação já grava agrupado.
