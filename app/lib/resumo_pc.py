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


def resumo_1024_por_cfop(session, competencia_id, tipo_operacao):
    """Resumo por CFOP a partir da Rotina 1024 (fonte primária da apuração) — soma todas as filiais da
    competência (grupo). base = valor_contabil - valor_icms; pis/cofins = base × alíquota, só para leitura
    (o cálculo oficial da apuração está em calculo_pis_cofins_lucro_real.calcular_apuracao_pc)."""
    rows = session.execute(text("""
        select r.cfop, coalesce(cpe.grupo, '(sem grupo)') as grupo, cp.descricao,
               count(distinct r.empresa_id) as n_filiais,
               sum(r.valor_contabil) as valor_contabil, sum(r.valor_icms) as valor_icms
        from resumo_1024_pc r
        left join cfop_pis_cofins_efetivo cpe on cpe.codigo = r.cfop
        left join cfop_pis_cofins cp on cp.codigo = r.cfop
        where r.competencia_id = :cid and r.tipo_operacao = :tipo
        group by r.cfop, cpe.grupo, cp.descricao
        order by r.cfop
    """), {"cid": competencia_id, "tipo": tipo_operacao}).mappings().all()
    df = pd.DataFrame(rows, columns=["cfop", "grupo", "descricao", "n_filiais", "valor_contabil", "valor_icms"])
    if not df.empty:
        df["base"] = df["valor_contabil"] - df["valor_icms"]
        df["valor_pis"] = (df["base"] * ALIQ_PIS).round(2)
        df["valor_cofins"] = (df["base"] * ALIQ_COFINS).round(2)
    return df


def resumo_por_cfop(session, competencia_id, tipo_operacao):
    rows = session.execute(text("""
        select ri.cfop, coalesce(cpe.grupo, '(sem grupo)') as grupo, cp.descricao,
               count(*) as n_itens, sum(ri.valor_itens) as valor_itens,
               sum(ri.valor_tributado) as valor_tributado, sum(ri.valor_pis) as valor_pis,
               sum(ri.valor_cofins) as valor_cofins
        from relatorio_pc_itens ri
        left join cfop_pis_cofins_efetivo cpe on cpe.codigo = ri.cfop
        left join cfop_pis_cofins cp on cp.codigo = ri.cfop
        where ri.competencia_id = :cid and ri.tipo_operacao = :tipo
        group by ri.cfop, cpe.grupo, cp.descricao
        order by ri.cfop
    """), {"cid": competencia_id, "tipo": tipo_operacao}).mappings().all()
    return pd.DataFrame(rows, columns=["cfop", "grupo", "descricao", "n_itens", "valor_itens",
                                        "valor_tributado", "valor_pis", "valor_cofins"])


def resumo_por_cst(session, competencia_id, tipo_operacao):
    rows = session.execute(text("""
        select ri.cst, cs.descricao,
               count(*) as n_itens, sum(ri.valor_itens) as valor_itens,
               sum(ri.valor_tributado) as valor_tributado, sum(ri.valor_pis) as valor_pis,
               sum(ri.valor_cofins) as valor_cofins
        from relatorio_pc_itens ri
        left join cst_pis_cofins cs on cs.codigo = ri.cst
        where ri.competencia_id = :cid and ri.tipo_operacao = :tipo
        group by ri.cst, cs.descricao
        order by ri.cst
    """), {"cid": competencia_id, "tipo": tipo_operacao}).mappings().all()
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
    rows = session.execute(text("""
        select id, tipo, cst, cfop, tipo_operacao, descricao, status, created_at
        from inconsistencias_pc
        where competencia_id = :cid
        order by (status = 'pendente') desc, tipo, cst, cfop
    """), {"cid": competencia_id}).mappings().all()
    return pd.DataFrame(rows, columns=["id", "tipo", "cst", "cfop", "tipo_operacao", "descricao", "status",
                                        "created_at"])


def marcar_inconsistencia(session, inconsistencia_id, status, usuario=None):
    usuario = usuario or {}
    session.execute(text("""
        update inconsistencias_pc
        set status = :status, revisado_por = :revisado_por, revisado_em = now()
        where id = :id
    """), {"status": status, "revisado_por": usuario.get("id"), "id": inconsistencia_id})
    session.commit()
