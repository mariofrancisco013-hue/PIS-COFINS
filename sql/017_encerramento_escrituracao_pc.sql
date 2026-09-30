-- ============================================================================================
-- MIGRAÇÃO 017 — Encerramento de competência e relatório da escrituração (Lucro Real) — 29/09/2026
-- ============================================================================================
-- Pedido do usuário: "crie um botão para exportar o relatório da escrituração daquele período encerrado.
-- O relatório deve conter tudo que foi utilizado para chegar nos valores do DARF de PIS e COFINS,
-- explicações, tabelas de consolidação de itens" + "o Excel deve ser informado como anexo".
--
-- Decisões (confirmadas com o usuário):
--   * Encerrar a competência usa o status 'fechada' que já existia no check de `competencias.status`
--     (001_schema.sql) e nunca tinha sido usado. Encerrada = não aceita mais importação, ajuste manual,
--     edição de item nem recálculo, até ser reaberta (com motivo registrado).
--   * No encerramento, a apuração é recalculada uma última vez e o relatório (PDF + Excel anexo) é gerado
--     e GRAVADO aqui — o download entrega sempre essa foto fixa, igual ao DARF daquele momento, mesmo que
--     depois alguma regra global (grupos de CFOP, NCMs LC 224, exceções) mude.
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase. É idempotente.

create table if not exists escrituracao_pc (
    id              bigserial primary key,
    competencia_id  bigint not null references competencias(id) on delete cascade,
    versao          integer not null,
    gerado_em       timestamptz not null default now(),
    gerado_por      text,
    pis_darf        numeric(14,2),
    cofins_darf     numeric(14,2),
    pdf             bytea not null,
    xlsx            bytea not null,
    unique (competencia_id, versao)
);
comment on table escrituracao_pc is
    'Relatório da escrituração PIS/COFINS gerado no encerramento da competência (PDF + Excel anexo). Uma '
    'versão nova a cada encerramento (reabrir e encerrar de novo gera a versão seguinte; as anteriores ficam '
    'como histórico). Ver migração 017.';
create index if not exists ix_escrituracao_pc_comp on escrituracao_pc (competencia_id, versao desc);

create table if not exists encerramento_pc_log (
    id              bigserial primary key,
    competencia_id  bigint not null references competencias(id) on delete cascade,
    acao            text not null check (acao in ('encerrar', 'reabrir')),
    usuario         text,
    motivo          text,
    em              timestamptz not null default now()
);
create index if not exists ix_encerramento_pc_log_comp on encerramento_pc_log (competencia_id, em desc);

alter table escrituracao_pc enable row level security;
drop policy if exists "authenticated_full_access" on escrituracao_pc;
create policy "authenticated_full_access" on escrituracao_pc for all to authenticated using (true) with check (true);

alter table encerramento_pc_log enable row level security;
drop policy if exists "authenticated_full_access" on encerramento_pc_log;
create policy "authenticated_full_access" on encerramento_pc_log for all to authenticated using (true) with check (true);
