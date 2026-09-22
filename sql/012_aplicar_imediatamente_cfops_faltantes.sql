-- ============================================================================================
-- APLICAÇÃO IMEDIATA (opcional) — registra os 4 CFOPs faltantes SEM esperar redeploy
-- ============================================================================================
-- Isto é um atalho: dá pra rodar isto agora, direto no SQL Editor do Supabase, para os CFOPs
-- 1912/5913/6551/6915 passarem a valer JÁ (mesmo efeito de usar a tela "CFOP × CST" → "Cadastrar/ajustar
-- CFOP" uma vez para cada um). `data/cfop_pis_cofins.csv` também foi atualizado com os mesmos 4 CFOPs,
-- então rodar `python scripts/seed_cfop_pis_cofins.py` no próximo deploy tem o MESMO efeito final — os
-- dois caminhos não conflitam (o seed só sobrescreve `grupo_padrao`, nunca `grupo_ajuste`).
insert into cfop_pis_cofins (codigo, descricao, direcao, grupo_padrao) values
    (1912, 'ENTRADA DE MERCADORIA OU BEM RECEBIDO PARA DEMONSTRACAO', 'entrada', '5.8'),
    (5913, 'RETORNO DE MERCADORIA RECEBIDA COM FIM ESPECIFICO DE EXPORTACAO (confirmar descricao oficial exata)', 'saida', '1.4'),
    (6551, 'VENDA DO ATIVO IMOBILIZADO', 'saida', '1.4'),
    (6915, 'REMESSA DE MERCADORIA OU BEM PARA CONSERTO OU REPARO (confirmar descricao oficial exata)', 'saida', '1.4')
on conflict (codigo) do update
    set descricao = excluded.descricao, direcao = excluded.direcao, grupo_padrao = excluded.grupo_padrao,
        updated_at = now();
