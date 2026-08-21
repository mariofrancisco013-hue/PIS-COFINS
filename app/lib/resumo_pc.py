"""
Leitura em grade dos dados importados — visão resumida por CFOP (Rotina 1024, fonte primária, e Relatório
1096, conferência) e visão analítica por item do 1096, usadas nas abas "Entrada"/"Saída" da página PIS/
COFINS Lucro Real. Sem granularidade de NF (nem o 1024 nem o 1096 trazem — ver metodologia no projeto), então
não há edição item a item aqui como no módulo ICMS: se um lançamento está errado, o certo é corrigir na
origem (Winthor/1024) e reimportar (com "substituir") — mais seguro do que editar um valor já calculado.
"""
import pandas as pd
from sqlalchemy import text

ALIQ_PIS = 0.0165
ALIQ_COFINS = 0.0760


def _clausula_cfops_permitidos(cfops_permitidos, alias, params, prefix="cfp"):
    """Filtro OPCIONAL e genérico por uma lista fechada de CFOPs — usado pela aba Entrada do Lucro Presumido
    (sessão de continuação, 20/08/2026: "na entrada considerar somente CFOP de devolução", confirmado que
    isso também vale para a GRADE/resumos, não só para a geração de inconsistências — ver
    cst_regras_pc.clausula_entrada_permitida_presumido para o equivalente usado nas checagens automáticas).
    `None` (padrão) = sem filtro nenhum — mantém o Lucro Real e a aba Saída do Presumido 100% inalterados."""
    if cfops_permitidos is None:
        return ""
    cfops = list(cfops_permitidos)
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(cfops)))
    for i, c in enumerate(cfops):
        params[f"{prefix}{i}"] = c
    return f" and {alias}.cfop in ({placeholders})"


def resumo_1024_por_cfop(session, competencia_id, tipo_operacao, cfops_permitidos=None):
    """Resumo por CFOP a partir da Rotina 1024 (fonte primária da apuração) — soma todas as filiais da
    competência (grupo). base = valor_contabil - valor_icms; pis/cofins = base × alíquota, só para leitura (o
    cálculo oficial da apuração está em calculo_pis_cofins_lucro_real.calcular_apuracao_pc — mesma fórmula,
    mantidas em sincronia). NOTA (18/08/2026): a exclusão de "Isentas/Não Tributadas" foi testada entre 14 e
    18/08 e revertida a pedido do usuário — a base voltou a ser só Valor Contábil − ICMS destacado.

    `cfops_permitidos` (opcional) restringe a uma lista fechada de CFOPs — ver `_clausula_cfops_permitidos`."""
    params = {"cid": competencia_id, "tipo": tipo_operacao}
    clausula = _clausula_cfops_permitidos(cfops_permitidos, "r", params)
    rows = session.execute(text(f"""
        select r.cfop, coalesce(cpe.grupo, '(sem grupo)') as grupo, cp.descricao,
               count(distinct r.empresa_id) as n_filiais,
               sum(r.valor_contabil) as valor_contabil, sum(r.valor_icms) as valor_icms
        from resumo_1024_pc r
        left join cfop_pis_cofins_efetivo cpe on cpe.codigo = r.cfop
        left join cfop_pis_cofins cp on cp.codigo = r.cfop
        where r.competencia_id = :cid and r.tipo_operacao = :tipo
          {clausula}
        group by r.cfop, cpe.grupo, cp.descricao
        order by r.cfop
    """), params).mappings().all()
    df = pd.DataFrame(rows, columns=["cfop", "grupo", "descricao", "n_filiais", "valor_contabil", "valor_icms"])
    if not df.empty:
        # sum(numeric) no Postgres volta como decimal.Decimal (via psycopg2), não float — Decimal * float
        # (ALIQ_PIS/ALIQ_COFINS) explode com TypeError dentro do pandas. Converte pra float antes de operar.
        df["valor_contabil"] = pd.to_numeric(df["valor_contabil"], errors="coerce").fillna(0.0)
        df["valor_icms"] = pd.to_numeric(df["valor_icms"], errors="coerce").fillna(0.0)
        df["base"] = df["valor_contabil"] - df["valor_icms"]
        df["valor_pis"] = (df["base"] * ALIQ_PIS).round(2)
        df["valor_cofins"] = (df["base"] * ALIQ_COFINS).round(2)
    return df


def resumo_por_cfop(session, competencia_id, tipo_operacao, cfops_permitidos=None):
    """`cfops_permitidos` (opcional) restringe a uma lista fechada de CFOPs — ver `_clausula_cfops_permitidos`."""
    params = {"cid": competencia_id, "tipo": tipo_operacao}
    clausula = _clausula_cfops_permitidos(cfops_permitidos, "ri", params)
    rows = session.execute(text(f"""
        select ri.cfop, coalesce(cpe.grupo, '(sem grupo)') as grupo, cp.descricao,
               count(*) as n_itens, sum(ri.valor_itens) as valor_itens,
               sum(ri.valor_tributado) as valor_tributado, sum(ri.valor_pis) as valor_pis,
               sum(ri.valor_cofins) as valor_cofins
        from relatorio_pc_itens ri
        left join cfop_pis_cofins_efetivo cpe on cpe.codigo = ri.cfop
        left join cfop_pis_cofins cp on cp.codigo = ri.cfop
        where ri.competencia_id = :cid and ri.tipo_operacao = :tipo
          {clausula}
        group by ri.cfop, cpe.grupo, cp.descricao
        order by ri.cfop
    """), params).mappings().all()
    return pd.DataFrame(rows, columns=["cfop", "grupo", "descricao", "n_itens", "valor_itens",
                                        "valor_tributado", "valor_pis", "valor_cofins"])


def resumo_por_cst(session, competencia_id, tipo_operacao, cfops_permitidos=None):
    """`cfops_permitidos` (opcional) restringe a uma lista fechada de CFOPs — ver `_clausula_cfops_permitidos`."""
    params = {"cid": competencia_id, "tipo": tipo_operacao}
    clausula = _clausula_cfops_permitidos(cfops_permitidos, "ri", params)
    rows = session.execute(text(f"""
        select ri.cst, cs.descricao,
               count(*) as n_itens, sum(ri.valor_itens) as valor_itens,
               sum(ri.valor_tributado) as valor_tributado, sum(ri.valor_pis) as valor_pis,
               sum(ri.valor_cofins) as valor_cofins
        from relatorio_pc_itens ri
        left join cst_pis_cofins cs on cs.codigo = ri.cst
        where ri.competencia_id = :cid and ri.tipo_operacao = :tipo
          {clausula}
        group by ri.cst, cs.descricao
        order by ri.cst
    """), params).mappings().all()
    return pd.DataFrame(rows, columns=["cst", "descricao", "n_itens", "valor_itens", "valor_tributado",
                                        "valor_pis", "valor_cofins"])


def carregar_itens(session, competencia_id, tipo_operacao, cfop_filtro=None, ncm_filtro=None, limite=1000):
    where = ["ri.competencia_id = :cid", "ri.tipo_operacao = :tipo"]
    params = {"cid": competencia_id, "tipo": tipo_operacao}
    if cfop_filtro:
        where.append("ri.cfop = :cfop")
        params["cfop"] = cfop_filtro
    if ncm_filtro:
        where.append("ri.ncm ilike :ncm_filtro")
        params["ncm_filtro"] = f"{ncm_filtro.strip()}%"
    where_sql = " and ".join(where)

    total = session.execute(text(f"select count(*) from relatorio_pc_itens ri where {where_sql}"), params).scalar()
    params["limite"] = limite
    rows = session.execute(text(f"""
        select ri.produto_codigo, ri.ncm, ri.cst, ri.cfop, ri.quantidade, ri.valor_contabil,
               ri.valor_desconto, ri.valor_itens, ri.valor_tributado, ri.aliq_pis, ri.valor_pis,
               ri.aliq_cofins, ri.valor_cofins, ri.valor_nao_tributado
        from relatorio_pc_itens ri
        where {where_sql}
        order by ri.cfop, ri.produto_codigo
        limit :limite
    """), params).mappings().all()
    df = pd.DataFrame(rows, columns=["produto_codigo", "ncm", "cst", "cfop", "quantidade", "valor_contabil",
                                      "valor_desconto", "valor_itens", "valor_tributado", "aliq_pis",
                                      "valor_pis", "aliq_cofins", "valor_cofins", "valor_nao_tributado"])
    return df, total


def carregar_inconsistencias(session, competencia_id):
    # fonte/empresa_id existem desde a migração 002 (multifilial) — podem vir nulas em registros antigos,
    # criados antes dessas colunas existirem (por isso o coalesce pra não quebrar o filtro na tela). ncm
    # existe desde a 004 (regras CST × CFOP/NCM). chave_agrupamento/quantidade/justificativa/
    # aplicada_por_excecao existem desde a 005 (agrupamento + aprendizado, estrutura igual ao módulo ICMS
    # normal) — coalesce(quantidade, 1) pra registros antigos sem agrupamento. O left join com ajustes_cst_pc
    # traz o último ajuste manual de CST registrado (se houver) — só para exibição/histórico, não influencia
    # cálculo nenhum (ver cst_regras_pc.registrar_ajuste_cst: é log-only).
    rows = session.execute(text("""
        select i.id, i.tipo, i.cst, i.cfop, i.ncm, i.tipo_operacao, i.descricao, i.status, i.created_at,
               coalesce(i.fonte, '(não identificada)') as fonte,
               i.empresa_id,
               coalesce(e.filial_winthor, '(não identificada)') as filial,
               i.chave_agrupamento, coalesce(i.quantidade, 1) as quantidade, i.justificativa,
               coalesce(i.aplicada_por_excecao, false) as aplicada_por_excecao,
               aj.cst_corrigido as ultimo_ajuste_cst, aj.observacao as ultimo_ajuste_obs,
               aj.ajustado_em as ultimo_ajuste_em
        from inconsistencias_pc i
        left join empresas e on e.id = i.empresa_id
        left join lateral (
            select a.cst_corrigido, a.observacao, a.ajustado_em
            from ajustes_cst_pc a
            where a.inconsistencia_id = i.id
            order by a.ajustado_em desc
            limit 1
        ) aj on true
        where i.competencia_id = :cid
        order by (i.status = 'pendente') desc, coalesce(i.quantidade, 1) desc, i.tipo, i.cst, i.cfop
    """), {"cid": competencia_id}).mappings().all()
    return pd.DataFrame(rows, columns=["id", "tipo", "cst", "cfop", "ncm", "tipo_operacao", "descricao",
                                        "status", "created_at", "fonte", "empresa_id", "filial",
                                        "chave_agrupamento", "quantidade", "justificativa",
                                        "aplicada_por_excecao", "ultimo_ajuste_cst", "ultimo_ajuste_obs",
                                        "ultimo_ajuste_em"])


def marcar_inconsistencia(session, inconsistencia_id, status, usuario=None):
    usuario = usuario or {}
    session.execute(text("""
        update inconsistencias_pc
        set status = :status, revisado_por = :revisado_por, revisado_em = now()
        where id = :id
    """), {"status": status, "revisado_por": usuario.get("id"), "id": inconsistencia_id})
    session.commit()
