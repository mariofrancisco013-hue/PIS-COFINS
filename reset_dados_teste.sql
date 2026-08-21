-- Apuração PIS/COFINS — zera os dados de TESTE (competências, importações, apuração calculada,
-- inconsistências, lançamentos manuais) para começar um teste real do zero.
--
-- O que ESTE script NÃO apaga (cadastro/referência, continua igual):
--   - empresas (cadastro do grupo)
--   - cfop_pis_cofins / cfop_pis_cofins_efetivo (tabela de CFOP × grupo da apuração)
--   - cst_pis_cofins / cst_pis_cofins_efetivo (tabela de CST)
--   - usuários (auth.users)
--
-- O que ESTE script APAGA (tudo que foi importado/calculado nos testes até agora):
--   - competencias  → e, por "on delete cascade", tudo que depende dela:
--       resumo_1024_pc (Rotina 1024 importada), relatorio_pc_itens (Relatório 1096 importado),
--       lancamentos_manuais_pc (Aluguéis/Depreciação lançados), apuracao_pc_linhas (resultado calculado),
--       saldo_credor_anterior_pc (saldo do período anterior digitado), inconsistencias_pc (achados).
--
-- Rode isto no SQL Editor do Supabase. É irreversível — confirme que é isso mesmo antes de rodar
-- (não tem como desfazer; se quiser manter algum período de teste específico, avise antes de rodar).

delete from competencias;

-- Reinicia os contadores de id (opcional, só estética — não afeta nada funcionalmente se pular esta parte).
alter sequence if exists competencias_id_seq restart with 1;
alter sequence if exists resumo_1024_pc_id_seq restart with 1;
alter sequence if exists relatorio_pc_itens_id_seq restart with 1;
alter sequence if exists lancamentos_manuais_pc_id_seq restart with 1;
alter sequence if exists apuracao_pc_linhas_id_seq restart with 1;
alter sequence if exists saldo_credor_anterior_pc_id_seq restart with 1;
alter sequence if exists inconsistencias_pc_id_seq restart with 1;

-- Conferência: deve retornar 0 linhas em tudo.
select 'competencias' as tabela, count(*) from competencias
union all select 'resumo_1024_pc', count(*) from resumo_1024_pc
union all select 'relatorio_pc_itens', count(*) from relatorio_pc_itens
union all select 'lancamentos_manuais_pc', count(*) from lancamentos_manuais_pc
union all select 'apuracao_pc_linhas', count(*) from apuracao_pc_linhas
union all select 'saldo_credor_anterior_pc', count(*) from saldo_credor_anterior_pc
union all select 'inconsistencias_pc', count(*) from inconsistencias_pc;
