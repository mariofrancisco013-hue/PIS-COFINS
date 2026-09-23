-- ============================================================================================
-- MIGRAÇÃO 014 — CFOP 5915 faltante em "1.4" + nenhuma mudança de schema para o fallback 1096
-- ============================================================================================
-- Contexto (sessão de continuação, 22/09/2026, ver claude/metodologia-pis-cofins-lucro-real.md, seção
-- "Causa raiz 6"): o usuário enviou a lista OFICIAL de CFOPs que devem compor "1.4 Outras Saídas" e
-- "5.8 Outras Entradas". Comparando com o cadastro atual, achou-se mais um CFOP faltante do lado saída:
-- **5915** ("Remessa de mercadoria ou bem para conserto ou reparo" — mesmo texto/operação do 6915, só que
-- para operação dentro do estado em vez de interestadual). Aplica-se aqui do mesmo jeito que 1912/5913/
-- 6551/6915 foram aplicados na migração 012.
--
-- Do lado entrada, a lista oficial do usuário tem 5 CFOPs A MENOS do que o cadastro atual de "5.8"
-- (1554, 2912, 2920, 2922, 2932) — o usuário pediu para NÃO mexer nisso ainda ("deixar como está por
-- enquanto, só investigar o valor"), então esta migração NÃO remove nem realoca esses 5 CFOPs. Fica
-- registrado aqui como pendência explícita — ver "Pontos em aberto" no doc do projeto.
--
-- Esta migração NÃO adiciona nenhuma coluna/tabela nova — o mecanismo de fallback 1096 (para CFOPs de
-- "1.4"/"5.8" totalmente ausentes da Rotina 1024 desta competência) é só código Python novo em
-- calculo_pis_cofins_lucro_real.py (_carregar_fallback_1096_cfops_ausentes_1024), sem exigir schema novo —
-- ele já reaproveita relatorio_pc_itens e cfop_pis_cofins_efetivo, que já existem.
insert into cfop_pis_cofins (codigo, descricao, direcao, grupo_padrao) values
    (5915, 'REMESSA DE MERCADORIA OU BEM PARA CONSERTO OU REPARO (confirmar descricao oficial exata)', 'saida', '1.4')
on conflict (codigo) do update
    set descricao = excluded.descricao, direcao = excluded.direcao, grupo_padrao = excluded.grupo_padrao,
        updated_at = now();
