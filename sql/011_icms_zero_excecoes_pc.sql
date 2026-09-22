-- ============================================================================================
-- MIGRAÇÃO 011 — Exceções pontuais de "ICMS = zero" (Lucro Real) — sessão de continuação, 22/09/2026
-- ============================================================================================
-- Contexto (ver claude/metodologia-pis-cofins-lucro-real.md, projeto Claude "PIS/COFINS", seções
-- "Causa raiz 1"/"Causa raiz 4" da sessão de 18-22/09/2026): alguns CFOP+CST específicos têm
-- `relatorio_pc_itens.valor_nao_tributado == valor_contabil` em TODOS os itens do CFOP (mesmo formato da
-- identidade Vl.Tributado = Vl.Contábil − Vl.Não Tributado), mas SEM nenhum ICMS real debitado/creditado
-- segundo o livro oficial (Rotina 1024/RAICMS) para aquele CFOP — nesses casos,
-- `_somar_icms_nao_excluido_por_cfop` estava tratando o valor inteiro do item como se fosse ICMS e
-- descontando por completo, o que:
--   (a) zerava/reduzia indevidamente a base líquida de grupos que NÃO são catch-all zerado (ex.: "1.2
--       Devolução de Mercadoria de Compra", CFOP 5411) — afeta o valor pago de verdade (DARF);
--   (b) inflava/reduzia indevidamente a EXIBIÇÃO das linhas "2.3"/"6.4" (ICMS Apuração - Destacado) — não
--       afeta o DARF (que já usa a base líquida certa por outro caminho), mas fazia a linha não bater com
--       o livro oficial.
--
-- Decisão do usuário (confirmada por AskUserQuestion, sessão de 18-22/09/2026): NÃO generalizar a regra
-- (ex.: "sempre que valor_nao_tributado == valor_contabil, tratar como ICMS zero") — o usuário preferiu
-- manter as listas CSTS_EXCLUSAO_ENTRADA/CSTS_EXCLUSAO_SAIDA como estão e tratar cada CFOP+CST confirmado
-- como uma EXCEÇÃO PONTUAL, cadastrada nesta tabela nova — mesmo padrão de tabela editável já usado para
-- `ncms_lc224_pc` (migração 009): sem UI dedicada por enquanto (editável direto no SQL Editor do Supabase,
-- mesma decisão já tomada para `ncms_lc224_pc`), extensível sem precisar mexer em código nem redeploy.
create table if not exists icms_zero_excecao_pc (
    id            bigserial primary key,
    cfop          integer not null,
    cst           integer not null,
    tipo_operacao text not null check (tipo_operacao in ('entrada', 'saida')),
    ativo         boolean not null default true,
    observacao    text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    unique (cfop, cst, tipo_operacao)
);
comment on table icms_zero_excecao_pc is
    'CFOP+CST específicos onde o Vl. Não Tributado do Relatório 1096 (usado por '
    '_somar_icms_nao_excluido_por_cfop como proxy do ICMS destacado do item) NÃO representa ICMS real — o '
    'livro RAICMS (Rotina 1024) mostra R$ 0,00 (ou um valor que o usuário decidiu ignorar por decisão de '
    'negócio) de ICMS para aquele CFOP. Excluído pontualmente da soma de "ICMS correto", sem alterar '
    'CSTS_EXCLUSAO_ENTRADA/CSTS_EXCLUSAO_SAIDA (calculo_pis_cofins_lucro_real.py). Editável direto aqui no '
    'SQL Editor — sem tela própria por enquanto, mesmo padrão hoje usado por ncms_lc224_pc.';

create index if not exists ix_icms_zero_excecao_pc_lookup
    on icms_zero_excecao_pc (tipo_operacao, cfop, cst) where ativo;

alter table icms_zero_excecao_pc enable row level security;
drop policy if exists "authenticated_full_access" on icms_zero_excecao_pc;
create policy "authenticated_full_access" on icms_zero_excecao_pc for all to authenticated using (true) with check (true);

-- Casos confirmados com o usuário até 22/09/2026 (achados no grupo Super Supply, CNPJ raiz 45.141.688,
-- competência 08/2026 — mas a exceção é cadastrada por CFOP+CST, e vale para QUALQUER grupo/competência
-- que tenha os mesmos códigos, não só para este caso concreto):
insert into icms_zero_excecao_pc (cfop, cst, tipo_operacao, observacao) values
    (5906, 49, 'saida',
     'Livro RAICMS: Imposto Debitado R$ 0,00 para este CFOP (100% "Outras") — confirmado com o PDF oficial '
     'da Rotina 1024 (filial 59, competência 08/2026). Decisão do usuário via AskUserQuestion.'),
    (5411, 49, 'saida',
     'Livro RAICMS: Imposto Debitado R$ 0,00 para este CFOP (100% "Outras") — confirmado com o PDF oficial '
     'da Rotina 1024 (filial 6, competência 08/2026). Decisão do usuário via AskUserQuestion.'),
    (6551, 70, 'saida',
     'Decisão de negócio do usuário: usar o valor cheio (Valor Contábil) do CFOP 6551, mesmo o livro '
     'RAICMS mostrando R$ 868,68 de ICMS debitado neste CFOP no mês de referência — confirmado por '
     'AskUserQuestion (opção "valor cheio, R$ 7.239,00").'),
    (6915, 1, 'saida',
     'Item único do CFOP (filial 6) com valor_nao_tributado == valor_contabil (R$ 603,00) — mesmo padrão '
     'de 5906/5411/6551, confirmado por AskUserQuestion em 22/09/2026.')
on conflict (cfop, cst, tipo_operacao) do nothing;
