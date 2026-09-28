-- ============================================================================================
-- MIGRAÇÃO 015 — Desativa a exceção 5411/CST49/saída em `icms_zero_excecao_pc` (fix13, 24/09/2026)
-- ============================================================================================
-- Contexto (ver claude/metodologia-pis-cofins-lucro-real-causa-raiz-8.md, projeto Claude "PIS/COFINS",
-- seção "8.7"): sessão de continuação de 24/09/2026, validação contra dados reais das Filiais 6/59
-- (uploads "saida 08.2026 supply f59 NOVO.xlsx" / "SAIDAS 08.2026 supply f6 NOVO.xlsx"). O usuário revisou
-- a exceção cadastrada na migração 011 para o CFOP 5411 (grupo "1.2", Devolução de Mercadoria de Compra,
-- NÃO catch-all) e decidiu REVERTER o tratamento especial: 5411 deve seguir a regra PADRÃO do grupo "1.2"
-- (sem exceção) — o ICMS real (valor_nao_tributado dos itens que não são CST 6/7) vai para "2.3"; itens
-- CST 6/7 (nenhum item de 5411 é CST 6/7 hoje) iriam para "2.7". Confirmado passo a passo com o usuário,
-- incluindo o efeito real no DARF: a base líquida do grupo "1.2" (Filial 6, competência 08/2026) cai de
-- R$ 8.706,09 para R$ 6.662,02 (R$ 2.044,07 a menos de base tributável, referente aos 2 itens do CFOP 5411
-- que são 100% isentos ao nível do item, ainda que o CFOP como um todo mostrasse ICMS zero no livro RAICMS).
--
-- IMPORTANTE: esta é uma mudança de DADO CADASTRAL (tabela `icms_zero_excecao_pc`), não de código — nenhuma
-- alteração foi feita em `calculo_pis_cofins_lucro_real.py` pra este ponto específico (Origem 1). O efeito
-- vale pra QUALQUER competência que tenha o CFOP 5411/CST49 na saída, não só a de referência (08/2026) —
-- avisado ao usuário antes de confirmar.
--
-- Optou-se por DESATIVAR (ativo = false) em vez de DELETAR a linha, preservando o histórico/observação
-- original (mesma lógica auditável já usada pra outras tabelas do sistema) — se o usuário quiser reverter
-- de novo no futuro, basta reativar (ativo = true) em vez de reinserir a linha.
update icms_zero_excecao_pc
set ativo = false,
    observacao = observacao || ' [DESATIVADA em 24/09/2026, fix13: usuário confirmou que o CFOP 5411 deve '
                 'seguir a regra padrão do grupo "1.2" (sem exceção pontual) — ver Causa raiz 8.7 na '
                 'metodologia. A exceção original (RAICMS mostrando R$ 0,00 de ICMS Debitado pra este CFOP) '
                 'permanece registrada abaixo, mas deixou de ser aplicada.]',
    updated_at = now()
where cfop = 5411 and cst = 49 and tipo_operacao = 'saida';
