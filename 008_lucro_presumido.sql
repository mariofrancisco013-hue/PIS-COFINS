-- Apuração PIS/COFINS — migração 008 (19/08/2026): cadastro de CFOP pro módulo Lucro Presumido (primeiro
-- grupo: Teresina Distribuidora, CNPJ 48.288.160/0001-04, já existia em data/empresas.csv com
-- regime='Lucro Presumido' — só o cálculo/tela são novos).
--
-- IMPORTANTE — por que isso é só "insert ... on conflict do nothing":
-- `cfop_pis_cofins.codigo` é chave primária ÚNICA por CFOP, compartilhada entre TODOS os grupos/regimes
-- (não tem coluna de módulo). O cálculo do Lucro Presumido (app/lib/calculo_pis_cofins_lucro_presumido.py)
-- NÃO depende desta tabela — usa listas fixas em Python (CFOPS_1_1/CFOPS_1_4/CFOPS_1_2_DEVOLUCAO_VENDA),
-- justamente para não arriscar sobrescrever a classificação já em produção usada pelo Lucro Real (alguns
-- CFOPs, como 5202/5411/6202, aparecem na planilha da Teresina como "devolução", um conceito que o Lucro
-- Real já pode classificar diferente). Rodar este insert só evita que esses CFOPs apareçam como falsa
-- inconsistência "CFOP sem grupo" na conferência do Relatório 1096 (ver
-- `importacao_pc._registrar_inconsistencias_1096`) — é só documentação/cadastro, não afeta nenhum valor já
-- calculado. Seguro rodar mesmo que parte já exista (não sobrescreve nada).
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase, depois do 001 ao 007.

insert into cfop_pis_cofins (codigo, descricao, direcao, grupo_padrao, observacao) values
    -- 1.1 — Faturamento Bruto (Mercadorias p/Revenda), saída
    (5102, 'Venda de mercadoria adquirida ou recebida de terceiros', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (5117, 'Venda de mercadoria adquirida ou recebida de terceiros, para consumidor final, com ST', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (5119, 'Venda de mercadoria adquirida ou recebida de terceiros, para entrega futura', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (5403, 'Venda de mercadoria sujeita a ST, na condição de contribuinte substituto', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (5405, 'Venda de mercadoria sujeita a ST, na condição de substituído', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (6102, 'Venda de mercadoria adquirida ou recebida de terceiros (outro estado)', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (6108, 'Venda de mercadoria adquirida ou recebida de terceiros, para não contribuinte', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (6117, 'Venda de mercadoria adquirida ou recebida de terceiros, para consumidor final, com ST (outro estado)', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (6119, 'Venda de mercadoria adquirida ou recebida de terceiros, para entrega futura (outro estado)', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (6120, 'Venda de mercadoria adquirida ou recebida de terceiros, remetida para industrialização por encomenda, não recebida do estabelecimento encomendante', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (6403, 'Venda de mercadoria sujeita a ST, na condição de contribuinte substituto (outro estado)', 'saida', '1.1', 'Lucro Presumido — Teresina'),
    (7102, 'Venda de mercadoria adquirida ou recebida de terceiros (exterior)', 'saida', '1.1', 'Lucro Presumido — Teresina'),

    -- 1.4 — Outras Saídas
    (5152, 'Transferência de mercadoria adquirida ou recebida de terceiros', 'saida', '1.4', 'Lucro Presumido — Teresina'),
    (5202, 'Devolução de compra para comercialização', 'saida', '1.4', 'Lucro Presumido — Teresina (aba PC da Teresina soma como "Outras Saídas"; Lucro Real pode classificar diferente — não sobrescreve se já existir)'),
    (5409, 'Venda de mercadoria sujeita ao regime de ST, cujo imposto já foi retido anteriormente', 'saida', '1.4', 'Lucro Presumido — Teresina'),
    (5411, 'Devolução de compra para industrialização em ST', 'saida', '1.4', 'Lucro Presumido — Teresina (idem 5202)'),
    (5910, 'Remessa em bonificação, doação ou brinde', 'saida', '1.4', 'Lucro Presumido — Teresina'),
    (5923, 'Remessa de mercadoria por conta e ordem de terceiros', 'saida', '1.4', 'Lucro Presumido — Teresina'),
    (5926, 'Lançamento efetuado em decorrência de emissão de documento fiscal relativo a operação ou prestação também registrada em equipamento ECF', 'saida', '1.4', 'Lucro Presumido — Teresina'),
    (5927, 'Baixa de estoque', 'saida', '1.4', 'Lucro Presumido — Teresina'),
    (5929, 'Lançamento efetuado em decorrência do desfazimento do negócio', 'saida', '1.4', 'Lucro Presumido — Teresina'),
    (5949, 'Outra saída de mercadoria ou prestação de serviço não especificado', 'saida', '1.4', 'Lucro Presumido — Teresina'),
    (6202, 'Devolução de compra para comercialização (outro estado)', 'saida', '1.4', 'Lucro Presumido — Teresina (idem 5202)'),
    (6923, 'Remessa de mercadoria por conta e ordem de terceiros (outro estado)', 'saida', '1.4', 'Lucro Presumido — Teresina'),

    -- 1.2 — Devolução de Venda (entrada) — mesmo conceito do "5.7 Devoluções de Vendas" do Lucro Real
    (1202, 'Devolução de venda de mercadoria adquirida ou recebida de terceiros', 'entrada', '5.7', 'Lucro Presumido — Teresina, linha "1.2 Devolução de Venda"'),
    (1411, 'Devolução de venda de mercadoria sujeita ao regime de ST', 'entrada', '5.7', 'Lucro Presumido — Teresina, linha "1.2 Devolução de Venda"'),
    (2202, 'Devolução de venda de mercadoria adquirida ou recebida de terceiros (outro estado)', 'entrada', '5.7', 'Lucro Presumido — Teresina, linha "1.2 Devolução de Venda"'),
    (2411, 'Devolução de venda de mercadoria sujeita ao regime de ST (outro estado)', 'entrada', '5.7', 'Lucro Presumido — Teresina, linha "1.2 Devolução de Venda"'),
    (3202, 'Devolução de venda de mercadoria adquirida ou recebida de terceiros (exterior)', 'entrada', '5.7', 'Lucro Presumido — Teresina, linha "1.2 Devolução de Venda"')
on conflict (codigo) do nothing;
