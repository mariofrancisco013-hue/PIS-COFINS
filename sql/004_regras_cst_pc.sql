-- Apuração PIS/COFINS — migração 004 (14/08/2026): regras de CST × CFOP/NCM pro Relatório 1096, mais o
-- fluxo de ajuste manual com histórico. Pedido do usuário: além do CST fora da tabela oficial (já existia),
-- checar se o CST batido em cada item do 1096 é o esperado para aquele CFOP ou NCM — ex: CST 70 (Aquisição
-- sem Direito a Crédito) só deveria aparecer em CFOPs específicos de compra; CST 71/74 (Isenção/Sem
-- Incidência) só em NCMs específicos. Achado = inconsistência (fonte='relatorio_1096', não bloqueia o
-- cálculo, que roda em cima da Rotina 1024) — igual ao cst_nao_mapeado/cfop_sem_grupo já existentes.
--
-- Rode este arquivo INTEIRO no SQL Editor do Supabase, depois do 001/002/003. Seguro de rodar de novo.

-- ============================================================================================
-- 0) Ajustes na inconsistencias_pc já existente (001_schema.sql):
--    - coluna ncm: as regras por NCM (cst_regra_ncm_pc) precisam registrar QUAL NCM do item bateu a regra
--      (a coluna cfop já existe, mas não tem onde guardar o NCM até agora).
--    - tipo: o check original só aceitava 'cst_nao_mapeado'/'cfop_sem_grupo' — as novas checagens desta
--      migração inserem 'cst_regra_cfop', 'cst_regra_ncm' e 'cst_regra_alerta', então o check precisa abrir
--      pra esses valores também (senão o insert quebra com "violates check constraint").
-- ============================================================================================
alter table inconsistencias_pc add column if not exists ncm text;

alter table inconsistencias_pc drop constraint if exists inconsistencias_pc_tipo_check;
alter table inconsistencias_pc add constraint inconsistencias_pc_tipo_check
    check (tipo in ('cst_nao_mapeado','cfop_sem_grupo','cst_regra_cfop','cst_regra_ncm','cst_regra_alerta'));

-- ============================================================================================
-- 1) Tabelas de regra — CST esperado por CFOP e por NCM. Extensíveis: adicionar uma nova regra é só
--    inserir uma linha aqui, sem mexer em código. Um CFOP/NCM só pode ter UMA regra por tipo_operacao
--    (não faz sentido o mesmo CFOP exigir dois CSTs diferentes) — por isso a unique constraint.
-- ============================================================================================
create table if not exists cst_regra_cfop_pc (
    id             bigserial primary key,
    cst            integer not null,
    cfop           integer not null,
    tipo_operacao  text not null check (tipo_operacao in ('entrada','saida')),
    observacao     text,
    created_at     timestamptz not null default now(),
    unique (cfop, tipo_operacao)
);
comment on table cst_regra_cfop_pc is
    'Regra: itens do Relatório 1096 com este CFOP (nesta direção) devem estar com este CST. Usada pela '
    'checagem de inconsistência cst_regra_cfop (ver app/lib/cst_regras_pc.py) — não afeta o cálculo, que '
    'roda sobre a Rotina 1024.';

create table if not exists cst_regra_ncm_pc (
    id             bigserial primary key,
    cst            integer not null,
    ncm            text not null,
    tipo_operacao  text not null check (tipo_operacao in ('entrada','saida')),
    observacao     text,
    created_at     timestamptz not null default now(),
    unique (ncm, tipo_operacao)
);
comment on table cst_regra_ncm_pc is
    'Regra: itens do Relatório 1096 com este NCM (nesta direção) devem estar com este CST. Mesma lógica da '
    'cst_regra_cfop_pc, só que por NCM em vez de CFOP (usada pros CSTs de isenção/sem incidência, que a '
    'Rotina 1024/CFOP não distingue sozinha).';

-- CST que deve sempre gerar alerta quando aparecer no 1096, mas nunca bloquear nada (ex.: CST 98 —
-- "alertar, mas não impeditivo", pedido do usuário). Sem CFOP/NCM associado — é qualquer ocorrência do CST.
create table if not exists cst_regra_alerta_pc (
    id             bigserial primary key,
    cst            integer not null,
    tipo_operacao  text not null check (tipo_operacao in ('entrada','saida')),
    observacao     text,
    created_at     timestamptz not null default now(),
    unique (cst, tipo_operacao)
);

-- ============================================================================================
-- 2) Regras confirmadas com o usuário em 14/08/2026 (à noite) — ver
--    claude/metodologia-pis-cofins-lucro-real.md para o histórico completo de cada uma.
-- ============================================================================================
insert into cst_regra_cfop_pc (cst, cfop, tipo_operacao, observacao) values
    (70, 1124, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 1407, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 1551, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 1556, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 1907, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 1910, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 1911, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 1933, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 1949, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2124, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2407, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2551, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2556, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2907, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2910, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2911, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2933, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (70, 2949, 'entrada', 'Operação de Aquisição sem Direito a Crédito'),
    (6, 5124, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5407, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5551, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5556, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5905, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5907, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5910, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5911, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5923, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5926, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5933, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 5949, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6124, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6407, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6551, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6556, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6905, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6907, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6910, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6911, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6923, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6926, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6933, 'saida', 'Espelho do CST 70 de entrada, lado saída'),
    (6, 6949, 'saida', 'Espelho do CST 70 de entrada, lado saída')
on conflict (cfop, tipo_operacao) do nothing;

insert into cst_regra_ncm_pc (cst, ncm, tipo_operacao, observacao) values
    (71, '09012100', 'entrada', 'Operação de Aquisição com Isenção'),
    (71, '17019900', 'entrada', 'Operação de Aquisição com Isenção'),
    (71, '22071090', 'entrada', 'Operação de Aquisição com Isenção'),
    (71, '22072019', 'entrada', 'Operação de Aquisição com Isenção'),
    (71, '22089000', 'entrada', 'Operação de Aquisição com Isenção'),
    (71, '33074900', 'entrada', 'Operação de Aquisição com Isenção'),
    (71, '34011190', 'entrada', 'Operação de Aquisição com Isenção'),
    (71, '34012010', 'entrada', 'Operação de Aquisição com Isenção'),
    (71, '49030000', 'entrada', 'Operação de Aquisição com Isenção'),
    (74, '22072019', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '28061020', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '28289011', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '28321010', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '29159050', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '32159000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '33074900', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34011190', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34011900', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34013000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34023990', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34025000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34029031', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34029039', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34029090', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '34042020', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '35061090', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '38085910', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '38089192', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '38089419', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '38089429', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '38089919', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '38099190', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '39191010', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '39231090', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '39232110', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '39232190', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '39233090', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '39241000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '39249000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '39261000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '40169990', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '42032900', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '48025610', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '48114110', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '48171000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '48181000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '48182000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '48201000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '52115900', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '53013000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '63071000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '68053090', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '82119390', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '83052000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '83059000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '84248990', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '84701000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '84729040', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '85234110', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '95030039', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '95030099', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '96031000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '96039000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '96081000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '96082000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '96089990', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (74, '96091000', 'entrada', 'Operação de Aquisição sem Incidência da Contribuição'),
    (7, '09012100', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '17019900', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '22071090', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '22072019', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '22089000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '28061020', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '28289011', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '28321010', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '29159050', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '32159000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '33074900', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34011190', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34011900', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34012010', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34013000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34023990', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34025000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34029031', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34029039', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34029090', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '34042020', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '35061090', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '38085910', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '38089192', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '38089419', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '38089429', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '38089919', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '38099190', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '39191010', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '39231090', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '39232110', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '39232190', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '39233090', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '39241000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '39249000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '39261000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '40169990', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '42032900', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '48025610', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '48114110', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '48171000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '48181000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '48182000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '48201000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '49030000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '52115900', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '53013000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '63071000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '68053090', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '82119390', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '83052000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '83059000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '84248990', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '84701000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '84729040', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '85234110', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '95030039', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '95030099', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '96031000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '96039000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '96081000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '96082000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '96089990', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída'),
    (7, '96091000', 'saida', 'União dos NCMs de CST 71+74 de entrada, lado saída')
on conflict (ncm, tipo_operacao) do nothing;

insert into cst_regra_alerta_pc (cst, tipo_operacao, observacao) values
    (98, 'entrada', 'CST 98 — alertar sempre que aparecer, mas nunca bloqueia o cálculo nem o fechamento da apuração.')
on conflict (cst, tipo_operacao) do nothing;

-- ============================================================================================
-- 3) Fluxo de ajuste manual com histórico. O usuário corrige o CST de uma inconsistência direto na tela —
--    isso NÃO muda nenhum valor calculado nem o CST gravado em relatorio_pc_itens (o cálculo continua
--    100% baseado na Rotina 1024) — é só um registro/log de "isso deveria ser corrigido no Winthor",
--    pra virar uma lista de correções a aplicar no sistema de origem.
-- ============================================================================================
create table if not exists ajustes_cst_pc (
    id                bigserial primary key,
    inconsistencia_id bigint not null references inconsistencias_pc(id) on delete cascade,
    cst_original       integer,
    cst_corrigido       integer not null,
    observacao         text,
    ajustado_por       uuid references auth.users(id),
    ajustado_em        timestamptz not null default now()
);
create index if not exists ix_ajustes_cst_pc_inconsistencia on ajustes_cst_pc(inconsistencia_id);
comment on table ajustes_cst_pc is
    'Histórico de correções manuais de CST feitas na tela de Inconsistências — não afeta cálculo nem dado '
    'importado, serve pra virar uma lista de "o que corrigir no Winthor" (rastreável: quem, quando, de que '
    'CST pra que CST).';

-- Novo status 'ajustado' pra distinguir de 'revisado' (só marcado como visto) — uma inconsistência de CST
-- corrigida via ajustes_cst_pc vira 'ajustado', mostrando na tela que já tem uma correção registrada.
alter table inconsistencias_pc drop constraint if exists inconsistencias_pc_status_check;
alter table inconsistencias_pc add constraint inconsistencias_pc_status_check
    check (status in ('pendente','revisado','ignorado','ajustado'));

-- ============================================================================================
-- 4) RLS — mesmo padrão do resto do schema (todo usuário autenticado tem acesso total).
-- ============================================================================================
alter table cst_regra_cfop_pc enable row level security;
alter table cst_regra_ncm_pc enable row level security;
alter table cst_regra_alerta_pc enable row level security;
alter table ajustes_cst_pc enable row level security;

do $$
declare
    t text;
begin
    for t in select unnest(array['cst_regra_cfop_pc', 'cst_regra_ncm_pc', 'cst_regra_alerta_pc', 'ajustes_cst_pc'])
    loop
        execute format('drop policy if exists "authenticated_full_access" on %I', t);
        execute format(
            'create policy "authenticated_full_access" on %I '
            'for all to authenticated using (true) with check (true)', t
        );
    end loop;
end $$;
