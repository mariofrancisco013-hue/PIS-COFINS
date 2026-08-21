-- Apuração PIS/COFINS — migração 007 (19/08/2026): pedido do usuário, mostrando o print da aba "Receitas
-- Financeiras" da planilha antiga — três coisas faltando na apuração calculada:
--   1) Excluir da base o valor da coluna "Outras" da Rotina 1024 (6ª coluna numérica de cada linha de CFOP
--      — já é capturada pelo parser desde sempre, mas descartada desde a reversão de 18/08/2026; ver
--      app/lib/importar_1024_pc.py). Precisa de uma coluna nova em resumo_1024_pc pra guardar esse valor.
--   2) Excluir da base o valor (Valor Contábil) dos itens do Relatório 1096 com CST 70/71/74 (entrada) e
--      CST 6/7 (saída) — esses CSTs não geram crédito/débito de PIS/COFINS, mas o CFOP deles pode estar
--      dentro de um grupo que a Rotina 1024 soma inteiro (ex.: CFOP 1407/1551/1556 fazem parte do grupo 5.8
--      "Outras Entradas"), então sem essa exclusão o valor desses itens infla a base indevidamente. Não
--      precisa de tabela nova — calculado on-the-fly a partir de relatorio_pc_itens (já existe).
--   3) Um jeito de lançar manualmente a base de Receitas Financeiras (linha 3, alíquota reduzida 0,65% PIS /
--      4% COFINS — Lei 8.426/2015), replicando os 6 subitens do print da planilha antiga (Desconto Obtido,
--      Variação Monetária, Rendimento de Aplicação, Juros recebidos, Multas recebidas, Outras Receitas).
--      Precisa de uma tabela nova (não reaproveita lancamentos_manuais_pc — lá as alíquotas são sempre as
--      cheias de crédito, 1,65%/7,60%; aqui é reduzida e é DÉBITO, não crédito).
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase, depois do 001 ao 006. Seguro de rodar de novo.

-- ============================================================================================
-- 1) RESUMO_1024_PC ganha valor_outras (6ª coluna numérica do PDF da Rotina 1024, "Outras").
--    Linhas já importadas ANTES desta migração ficam com valor_outras = 0 (mesma limitação já documentada
--    para "Isentas/Não Tributadas" em 14-18/08/2026: não dá pra "consertar" um valor não gravado sem o PDF
--    original) — para essas competências, reimporte a Rotina 1024 com "substituir" se quiser que a
--    exclusão de "Outras" reflita o valor real em vez de zero.
-- ============================================================================================
alter table resumo_1024_pc add column if not exists valor_outras numeric(14,2) not null default 0;

-- ============================================================================================
-- 2) RECEITAS_FINANCEIRAS_PC — um valor por (competência, subitem), igual ao padrão de
--    saldo_credor_anterior_pc (upsert, não é uma lista de lançamentos como lancamentos_manuais_pc, porque
--    aqui cada subitem é UM total mensal, não vários lançamentos avulsos).
-- ============================================================================================
create table if not exists receitas_financeiras_pc (
    id                    bigserial primary key,
    competencia_id        bigint not null references competencias(id) on delete cascade,
    tipo                  text not null check (tipo in (
        'desconto_obtido', 'variacao_monetaria', 'rendimento_aplicacao', 'juros_recebidos',
        'multas_recebidas', 'outras_receitas'
    )),
    valor                 numeric(14,2) not null default 0,
    atualizado_por        uuid references auth.users(id),
    atualizado_por_email  text,
    updated_at            timestamptz not null default now(),
    unique (competencia_id, tipo)
);
create index if not exists ix_receitas_financeiras_pc_competencia on receitas_financeiras_pc(competencia_id);
comment on table receitas_financeiras_pc is
    'Base mensal de Receitas Financeiras (Lei 8.426/2015, PIS 0,65% / COFINS 4%), um valor por subitem '
    '(3.1 a 3.6 da planilha antiga) — soma dos 6 vira a base da linha 3 da apuração. Débito (aumenta o que '
    'se paga), diferente de lancamentos_manuais_pc que só cobre crédito nas alíquotas cheias.';

alter table receitas_financeiras_pc enable row level security;
drop policy if exists "authenticated_full_access" on receitas_financeiras_pc;
create policy "authenticated_full_access" on receitas_financeiras_pc
    for all to authenticated using (true) with check (true);

-- Não precisa de backfill: valor_outras=0 é o comportamento equivalente a "não excluir nada" (mesmo de
-- antes desta migração), e receitas_financeiras_pc começa vazia (linha 3 continua em R$ 0,00 até alguém
-- preencher os subitens pela aba Ajustes Manuais).
