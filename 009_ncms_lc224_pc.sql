-- Apuração PIS/COFINS — migração 009 (20/08/2026): tabela de NCMs alcançados pela Lei Complementar
-- 224/2025 (incidência residual de PIS/COFINS sobre produtos hoje isentos — CST 6/7 de saída). Substitui a
-- lista fixa que estava hardcoded em calculo_pis_cofins_lucro_presumido.py/calculo_pis_cofins_lucro_real.py
-- (linhas "3.1" e "4", respectivamente) — pedido do usuário em 20/08/2026: "vira fonte do cálculo
-- (editável)" direto no Supabase, sem precisar editar código nem reimplantar o app pra adicionar/remover
-- NCM ou mudar alíquota.
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase, depois do 001-008. Seguro de rodar de novo (os
-- inserts de seed usam "on conflict do nothing").

create table if not exists ncms_lc224_pc (
    id             bigserial primary key,
    ncm            text not null,
    regime         text not null check (regime in ('presumido', 'real')),
    aliq_pis       numeric(9,6) not null,
    aliq_cofins    numeric(9,6) not null,
    ativo          boolean not null default true,
    observacao     text,
    created_at     timestamptz not null default now(),
    unique (ncm, regime)
);
comment on table ncms_lc224_pc is
    'NCMs com incidência residual de PIS/COFINS sobre produtos isentos (CST 6/7 de saída), Lei '
    'Complementar 224/2025 — usada por calcular_apuracao_pc_presumido (linha "3.1") e calcular_apuracao_pc '
    '(linha "4"). Uma linha por (ncm, regime) porque as alíquotas diferem entre Presumido e Real. Editar '
    'aqui (inserir NCM novo, desativar um existente, mudar alíquota) reflete na próxima vez que a Apuração '
    'for recalculada — não precisa mexer em código nem reimplantar o app. NCM gravado com zero à esquerda '
    'quando aplicável (ex.: "09012100") — o cálculo casa contra relatorio_pc_itens.ncm independente disso '
    '(ver _variantes_ncm nos dois módulos de cálculo).';
comment on column ncms_lc224_pc.ativo is
    'false = desativa sem apagar o histórico/cadastro (ex.: NCM que deixou de estar na lista da lei) — a '
    'apuração só considera linhas com ativo=true.';

insert into ncms_lc224_pc (ncm, regime, aliq_pis, aliq_cofins, observacao) values
    ('33074900', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('34011190', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('48181000', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('49019900', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('09012100', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('17019900', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('33049990', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('22072019', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('49030000', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('22071090', 'presumido', 0.000650, 0.003000, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('33074900', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('34011190', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('48181000', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('49019900', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('09012100', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('17019900', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('33049990', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('22072019', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('49030000', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026'),
    ('22071090', 'real',      0.001650, 0.007600, 'LC 224/2025 — informado pelo usuário em 20/08/2026')
on conflict (ncm, regime) do nothing;
