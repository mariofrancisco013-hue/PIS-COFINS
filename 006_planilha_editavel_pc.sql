-- Apuração PIS/COFINS — migração 006 (18/08/2026, à noite): grade editável nas abas Saída/Entrada +
-- "CFOPs sem Checagem de CST" — pedido do usuário: "quero mais ou menos [a] estrutura" do módulo ICMS
-- Normal (grade tipo planilha, banner de status, abas de cadastro de regra) trazida pro PIS/COFINS.
--
-- IMPORTANTE (documentado também no código e na metodologia do projeto): diferente do ICMS Normal, aqui a
-- grade edita `relatorio_pc_itens` (Relatório 1096), que é só CONFERÊNCIA — editar um item aqui NUNCA muda
-- a Apuração (linhas 1.x-11.x), que continua rodando 100% sobre `resumo_1024_pc` (Rotina 1024). O efeito de
-- editar a grade é só recalcular as inconsistências de CST × CFOP/NCM (aba Inconsistências) e a Conferência
-- 1024×1096 — ver `app/lib/planilha_pc.py`.
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase, depois do 001 ao 005. Seguro de rodar de novo.

-- ============================================================================================
-- 1) Auditoria das edições feitas na grade "planilha" de Saída/Entrada — mesmo padrão de
--    auditoria_edicoes_planilha do módulo ICMS Normal, adaptado para relatorio_pc_itens.
-- ============================================================================================
create table if not exists auditoria_edicoes_pc (
    id                bigserial primary key,
    item_id           bigint not null references relatorio_pc_itens(id) on delete cascade,
    competencia_id    bigint not null references competencias(id) on delete cascade,
    tipo_operacao     text not null check (tipo_operacao in ('entrada','saida')),
    campo             text not null,
    valor_anterior    text,
    valor_novo        text,
    editado_por       uuid references auth.users(id),
    editado_por_email text,
    editado_em        timestamptz not null default now()
);
create index if not exists ix_auditoria_edicoes_pc_comp on auditoria_edicoes_pc(competencia_id, tipo_operacao);
create index if not exists ix_auditoria_edicoes_pc_item on auditoria_edicoes_pc(item_id);
comment on table auditoria_edicoes_pc is
    'Histórico de edições feitas direto na grade das abas Saída/Entrada (CFOP, NCM, valores) — uma linha '
    'por CAMPO alterado. Só afeta relatorio_pc_itens (Relatório 1096, conferência); NÃO afeta a Apuração, '
    'que continua rodando sobre resumo_1024_pc (Rotina 1024).';

-- ============================================================================================
-- 2) CFOPs sem checagem de CST — por filial, mesmo padrão de cfops_sem_validacao do módulo ICMS Normal.
--    Itens desse CFOP deixam de entrar nas 3 checagens automáticas de cst_regras_pc.py (cst_regra_cfop/
--    cst_regra_ncm/cst_regra_alerta) para esta filial, até o cadastro ser removido. Complementa (não
--    substitui) as exceções por chave_agrupamento da migração 005: aqui é "não checar mais este CFOP
--    inteiro"; lá é "não avisar de novo sobre este erro específico".
-- ============================================================================================
create table if not exists cfops_sem_checagem_cst_pc (
    id                bigserial primary key,
    empresa_id        bigint not null references empresas(id) on delete cascade,
    cfop              integer not null,
    motivo            text,
    criado_por        uuid references auth.users(id),
    criado_por_email  text,
    created_at        timestamptz not null default now(),
    unique (empresa_id, cfop)
);
create index if not exists ix_cfops_sem_checagem_cst_pc_empresa on cfops_sem_checagem_cst_pc(empresa_id);
comment on table cfops_sem_checagem_cst_pc is
    'CFOPs marcados como "não precisa checar CST" por filial — usada por cst_regras_pc.py para ignorar '
    'itens desses CFOPs nas 3 checagens automáticas de CST × CFOP/NCM. Não afeta a Planilha (os itens '
    'continuam aparecendo normalmente) nem a Apuração, só as checagens automáticas.';

alter table auditoria_edicoes_pc enable row level security;
drop policy if exists "authenticated_full_access" on auditoria_edicoes_pc;
create policy "authenticated_full_access" on auditoria_edicoes_pc
    for all to authenticated using (true) with check (true);

alter table cfops_sem_checagem_cst_pc enable row level security;
drop policy if exists "authenticated_full_access" on cfops_sem_checagem_cst_pc;
create policy "authenticated_full_access" on cfops_sem_checagem_cst_pc
    for all to authenticated using (true) with check (true);

-- Não precisa de backfill: as duas tabelas começam vazias — auditoria só registra edições feitas a partir
-- de agora, e nenhuma filial tem CFOP marcado como "sem checagem" ainda (cadastro é feito pela tela nova).
