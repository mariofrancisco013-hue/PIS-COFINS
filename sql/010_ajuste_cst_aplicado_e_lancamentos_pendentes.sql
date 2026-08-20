-- Sessão de continuação de 20/08/2026 — dois pedidos do usuário no mesmo dia:
--
-- 1) "Ajustar CST" na aba Inconsistências passa a poder corrigir de verdade (não só histórico) — ver
--    `app/lib/cst_regras_pc.aplicar_ajuste_cst`/`escopo_ajuste_seguro`. A tabela `ajustes_cst_pc` (migração
--    004) ganha uma coluna `aplicado` pra distinguir os dois caminhos: true = corrigiu relatorio_pc_itens.cst
--    de verdade (escopo inequívoco: CST fora da tabela oficial, ou CFOP/NCM específico); false = só
--    histórico/checklist (escopo ambíguo — mesmo CST espalhado por vários CFOPs/NCMs diferentes, sem um
--    único CFOP/NCM que valha pra todos os itens do grupo).
--
-- 2) "Criar lançamento manual" pras linhas que ficavam ⏳ pendente sem nenhum campo pra preencher — ver
--    docstring de `app/lib/lancamentos_manuais_pc.py`. A tabela `lancamentos_manuais_pc` (migração 001) tinha
--    um CHECK restringindo `tipo` aos 3 valores originais (Aluguéis/Depreciação) — precisa abrir pros 7 tipos
--    novos do Lucro Real e 5 do Lucro Presumido (esse regime não tinha lançamento manual nenhum até agora).

alter table ajustes_cst_pc add column if not exists aplicado boolean not null default false;
comment on column ajustes_cst_pc.aplicado is
    'true = corrigiu relatorio_pc_itens.cst de verdade (aplicar_ajuste_cst, escopo inequívoco — CST fora da '
    'tabela oficial ou CFOP/NCM específico). false = só histórico/checklist pra corrigir no Winthor '
    '(registrar_ajuste_cst, escopo ambíguo — mesmo CST em vários CFOPs/NCMs diferentes). Ajustes registrados '
    'ANTES desta migração ficam com aplicado=false por padrão — reflete o comportamento real deles (nenhum '
    'tocou relatorio_pc_itens).';

alter table lancamentos_manuais_pc drop constraint if exists lancamentos_manuais_pc_tipo_check;
alter table lancamentos_manuais_pc add constraint lancamentos_manuais_pc_tipo_check
    check (tipo in (
        -- originais (14/08/2026)
        'aluguel_predio_credito', 'aluguel_maquinas_credito', 'depreciacao_credito',
        -- Lucro Real, novos em 20/08/2026 — ver LAYOUT_LINHAS em calculo_pis_cofins_lucro_real.py
        'servicos_debito', 'aluguel_recebido_debito', 'fretes_supply_log_credito',
        'icms_substituicao_exclusao', 'exportacao_debito_exclusao', 'ipi_exclusao',
        'exportacao_credito_exclusao',
        -- Lucro Presumido, novos em 20/08/2026 — regime não tinha lançamento manual nenhum até aqui
        'servicos_debito_presumido', 'aluguel_recebido_debito_presumido', 'demais_receitas_debito_presumido',
        'monofasica_exclusao_presumido', 'exportacao_exclusao_presumido'
    ));
