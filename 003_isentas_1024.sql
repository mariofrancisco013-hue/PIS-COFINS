-- Apuração PIS/COFINS — migração 003 (14/08/2026): a Rotina 1024 também traz, por CFOP, o valor de
-- "Isentas/Não Tributadas" (5ª coluna numérica da linha, ao lado do ICMS destacado) e "Outras" (6ª coluna).
-- O parser já lia essas duas colunas do PDF mas descartava os valores — só guardava Valor Contábil, Base de
-- Cálculo do ICMS e o ICMS destacado. Confirmado com o usuário em 14/08/2026: a base do PIS/COFINS é
--   Valor Contábil − ICMS destacado − Isentas/Não Tributadas
-- (não só "Valor Contábil − ICMS destacado" como estava até agora) — por isso a Conferência 1024×1096
-- divergia sempre que havia CFOP com venda/compra isenta misturada com tributada.
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase, depois do 001 e do 002. Seguro de rodar de novo.

alter table resumo_1024_pc add column if not exists valor_isentas_nao_tributadas numeric(14,2) not null default 0;
comment on column resumo_1024_pc.valor_isentas_nao_tributadas is
    'Coluna "Isentas/Não Tributadas" da Rotina 1024 (5ª coluna numérica da linha do CFOP) — entra na base '
    'do PIS/COFINS como uma exclusão, junto com o ICMS destacado: base = valor_contabil - valor_icms - '
    'valor_isentas_nao_tributadas.';

alter table resumo_1024_pc add column if not exists valor_outras numeric(14,2) not null default 0;
comment on column resumo_1024_pc.valor_outras is
    'Coluna "Outras" da Rotina 1024 (6ª e última coluna numérica da linha do CFOP) — guardada para '
    'referência/transparência, mas não é usada na base do PIS/COFINS nesta versão.';

-- Linhas já importadas antes desta migração ficam com valor_isentas_nao_tributadas = 0 (backfill não é
-- possível — o PDF original teria que ser reimportado). Se você já tem competências calculadas com a
-- Rotina 1024 anterior a esta migração, reimporte o PDF de cada filial com "substituir" marcado e recalcule
-- a apuração, senão a base fica sem a exclusão das isentas até lá.
