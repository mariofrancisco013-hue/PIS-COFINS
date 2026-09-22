-- ============================================================================================
-- MIGRAÇÃO 013 — Base de PIS/COFINS por CFOP: Relatório 1096 em vez da Rotina 1024 (sessão de continuação,
-- 22/09/2026)
-- ============================================================================================
-- Achado real (grupo Super Supply, competência 08/2026, ver claude/metodologia-pis-cofins-lucro-real.md,
-- projeto Claude "PIS/COFINS", seção "Causa raiz 5"): CFOPs de AQUISIÇÃO DE SERVIÇO tributado pelo ISSQN
-- (1933/2933) têm Valor Contábil muito menor na Rotina 1024 (livro de apuração do ICMS) do que no
-- Relatório 1096 (relatório operacional completo do Winthor) — confirmado com consulta direta ao banco:
-- CFOP 1933, competência 08/2026, Filial 6: R$ 6.558,26 na Rotina 1024 vs. R$ 316.676,33 no Relatório 1096
-- (diferença de R$ 310.118,07). Isso é ESPERADO estruturalmente, não é erro de importação: ISSQN é imposto
-- municipal, não ICMS — o livro RAICMS simplesmente não foi desenhado para capturar o valor cheio de uma
-- aquisição de serviço, então ele reflete só um resíduo/ajuste, não a operação real.
--
-- Decisão do usuário (confirmada por AskUserQuestion): para CFOPs marcados aqui, a base de PIS/COFINS
-- (Valor Contábil usado em _base_por_grupo) passa a vir do Relatório 1096 em vez da Rotina 1024. Como estes
-- CFOPs pertencem ao grupo catch-all "5.8" (zerado por inteiro, não gera crédito de PIS/COFINS de verdade
-- — ver calculo_pis_cofins_lucro_real.py), isto NÃO muda o DARF calculado; só corrige o valor EXIBIDO na
-- linha "5.8 Outras Entradas" para bater com a operação real (e com a planilha de conferência do usuário).
alter table cfop_pis_cofins add column if not exists usa_base_1096 boolean not null default false;
comment on column cfop_pis_cofins.usa_base_1096 is
    'true = a base de PIS/COFINS deste CFOP vem do Relatório 1096 (relatorio_pc_itens.valor_contabil), não '
    'da Rotina 1024 (resumo_1024_pc.valor_contabil) — usar para CFOPs onde a Rotina 1024 (livro de ICMS) '
    'não reflete o valor real da operação, como aquisição de serviço tributado pelo ISSQN (não é ICMS). '
    'Ver _carregar_override_1096_por_cfop em calculo_pis_cofins_lucro_real.py.';

-- A view cfop_pis_cofins_efetivo precisa expor a coluna nova para o cálculo conseguir ler.
create or replace view cfop_pis_cofins_efetivo as
    select codigo, descricao, direcao, coalesce(grupo_ajuste, grupo_padrao) as grupo, observacao,
           usa_base_1096
    from cfop_pis_cofins;

-- Casos confirmados com o usuário em 22/09/2026:
update cfop_pis_cofins set usa_base_1096 = true, updated_at = now()
    where codigo in (1933, 2933);
