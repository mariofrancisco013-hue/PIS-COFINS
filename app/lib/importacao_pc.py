"""
Importação de dados para a apuração de PIS/COFINS — Lucro Real.

Desde 14/08/2026 a apuração é feita por GRUPO (CNPJ raiz — matriz + filiais consolidadas), não mais por uma
empresa isolada, e a fonte PRIMÁRIA do cálculo é a Rotina 1024 (ver `app/lib/importar_1024_pc.py`), uma por
filial. O Relatório 1096 ("Relatório por combinação de CFOP, CST, NCM e alíquota - Analítico" — Entrada/
Saída) continua sendo importado, mas agora só para conferência por CFOP (ver `calculo_pis_cofins_lucro_real.
conferencia_1024_x_1096`) e para a checagem de CST fora da tabela oficial — não alimenta mais a apuração
diretamente. Ver metodologia completa em `claude/metodologia-pis-cofins-lucro-real.md` no projeto
"PIS/COFINS".

IMPORTANTE: o Relatório 1096 ("Report", sem cabeçalho, 14 colunas) NÃO traz o número da NF — só o relatório
impresso/agrupado por bloco de NF traz isso.
"""
import pandas as pd
from sqlalchemy import text

from lib.cst_regras_pc import registrar_inconsistencias_cst_regras, clausula_entrada_permitida_presumido

COLS = [
    "produto_codigo", "ncm", "cst", "cfop", "quantidade", "valor_contabil", "valor_desconto",
    "valor_itens", "valor_tributado", "aliq_pis", "valor_pis", "aliq_cofins", "valor_cofins",
    "valor_nao_tributado",
]

COLS_TABELA = ["competencia_id", "empresa_id", "tipo_operacao"] + COLS


# ---------------------------------------------------------------------------------------------- Competência (grupo)
def buscar_competencia_grupo(session, cnpj_raiz, ano, mes, modulo="pis_cofins_lucro_real"):
    """Só CONSULTA — devolve o id da competência do grupo (cnpj_raiz) se já existir, ou None."""
    return session.execute(text("""
        select id from competencias where cnpj_raiz=:raiz and ano=:ano and mes=:mes and modulo=:modulo
    """), {"raiz": cnpj_raiz, "ano": ano, "mes": mes, "modulo": modulo}).scalar()


def get_or_create_competencia_grupo(session, cnpj_raiz, ano, mes, modulo="pis_cofins_lucro_real"):
    comp = buscar_competencia_grupo(session, cnpj_raiz, ano, mes, modulo)
    if comp:
        return comp
    result = session.execute(text("""
        insert into competencias (cnpj_raiz, ano, mes, modulo, status)
        values (:raiz, :ano, :mes, :modulo, 'aberta') returning id
    """), {"raiz": cnpj_raiz, "ano": ano, "mes": mes, "modulo": modulo})
    novo_id = result.fetchone()[0]
    session.commit()
    return novo_id


def listar_grupos(session, regime_like="Lucro Real%"):
    """Um grupo = um cnpj_raiz. Nome de referência = a empresa com 'Matriz' no nome, se houver, senão a
    primeira em ordem alfabética — só para rotular a caixa de seleção, não afeta o cálculo."""
    rows = session.execute(text("""
        select e.cnpj_raiz,
               coalesce(
                   (select e2.razao_social from empresas e2
                    where e2.cnpj_raiz = e.cnpj_raiz and e2.razao_social ilike '%matriz%'
                    order by e2.razao_social limit 1),
                   min(e.razao_social)
               ) as nome_grupo,
               count(*) as n_filiais
        from empresas e
        where e.regime ilike :regime
        group by e.cnpj_raiz
        order by nome_grupo
    """), {"regime": regime_like}).mappings().all()
    return [dict(r) for r in rows]


def listar_filiais_grupo(session, cnpj_raiz):
    rows = session.execute(text("""
        select id, filial_winthor, razao_social, cnpj
        from empresas where cnpj_raiz = :raiz
        order by filial_winthor nulls last, razao_social
    """), {"raiz": cnpj_raiz}).mappings().all()
    return [dict(r) for r in rows]


def status_filiais_grupo(session, cnpj_raiz, ano, mes, modulo="pis_cofins_lucro_real"):
    """Uma linha por filial do grupo, com o que já foi importado nesta competência (se ela existir) — usado
    na tela de Importar Relatórios para mostrar o que falta antes de calcular a apuração consolidada."""
    filiais = listar_filiais_grupo(session, cnpj_raiz)
    competencia_id = buscar_competencia_grupo(session, cnpj_raiz, ano, mes, modulo)
    if not competencia_id:
        return [{**f, "cfops_1024": 0, "itens_1096_entrada": 0, "itens_1096_saida": 0} for f in filiais], None

    contagem_1024 = dict(session.execute(text("""
        select empresa_id, count(*) from resumo_1024_pc where competencia_id = :cid group by empresa_id
    """), {"cid": competencia_id}).all())
    contagem_1096 = session.execute(text("""
        select empresa_id, tipo_operacao, count(*) as n
        from relatorio_pc_itens where competencia_id = :cid group by empresa_id, tipo_operacao
    """), {"cid": competencia_id}).mappings().all()
    entrada_1096, saida_1096 = {}, {}
    for r in contagem_1096:
        if r["tipo_operacao"] == "entrada":
            entrada_1096[r["empresa_id"]] = r["n"]
        else:
            saida_1096[r["empresa_id"]] = r["n"]

    out = []
    for f in filiais:
        out.append({
            **f,
            "cfops_1024": contagem_1024.get(f["id"], 0),
            "itens_1096_entrada": entrada_1096.get(f["id"], 0),
            "itens_1096_saida": saida_1096.get(f["id"], 0),
        })
    return out, competencia_id


# ---------------------------------------------------------------------------------------------- Relatório 1096 (conferência)
def checar_duplicacao(session, competencia_id, empresa_id, tipos, substituir):
    """Escopado por filial (empresa_id) — múltiplas filiais convivem na mesma competência (grupo), então
    reimportar o 1096 de uma filial não pode mexer nos itens já importados de outra."""
    placeholders = ", ".join(f":t{i}" for i in range(len(tipos)))
    params = {f"t{i}": t for i, t in enumerate(tipos)}
    params["cid"] = competencia_id
    params["eid"] = empresa_id

    n = session.execute(
        text(f"select count(*) from relatorio_pc_itens where competencia_id = :cid and empresa_id = :eid "
             f"and tipo_operacao in ({placeholders})"),
        params,
    ).scalar()
    if n and not substituir:
        raise ValueError(
            f"Esta filial já tem {n} itens de {'/'.join(tipos)} (Relatório 1096) importados para esta "
            f"competência. Marque 'substituir' se este é um relatório corrigido (evita duplicar). Isso NÃO "
            f"afeta outras filiais nem o outro tipo (Entrada/Saída) já importado."
        )
    if n and substituir:
        session.execute(text("""
            delete from inconsistencias_pc where competencia_id = :cid and fonte = 'relatorio_1096'
        """), {"cid": competencia_id})
        session.execute(
            text(f"delete from relatorio_pc_itens where competencia_id = :cid and empresa_id = :eid "
                 f"and tipo_operacao in ({placeholders})"),
            params,
        )
        session.commit()
    return n or 0


def _preparar_dataframe(arquivo, tipo_operacao, competencia_id, empresa_id):
    """Lê o .xlsx do Relatório 1096 (aba 'Report', sem cabeçalho, 14 colunas posicionais) e devolve um
    DataFrame já no formato da tabela `relatorio_pc_itens`, pronto para to_sql."""
    # engine="calamine": o Winthor às vezes exporta esse relatório como .xlsx gerado por uma ferramenta
    # interna ("ReportBuilder") com XML fora do padrão OOXML — openpyxl trava com TypeError nesses casos
    # (mesmo achado documentado no módulo ICMS, app/lib/importacao.py). calamine lê os dois formatos sem
    # validar essa parte do XML.
    df = pd.read_excel(arquivo, sheet_name="Report", header=None, engine="calamine")
    if len(df.columns) != len(COLS):
        raise ValueError(
            f"Arquivo de {tipo_operacao} tem {len(df.columns)} colunas, esperado {len(COLS)}. O layout do "
            f"Relatório 1096 pode ter mudado — confira antes de importar."
        )
    df.columns = COLS

    cfop_vazio = pd.to_numeric(df["cfop"], errors="coerce").isna()
    if cfop_vazio.any():
        tem_valor = cfop_vazio & (pd.to_numeric(df["valor_itens"], errors="coerce").fillna(0) != 0)
        if tem_valor.any():
            exemplos = df.loc[tem_valor, ["produto_codigo", "ncm", "valor_itens"]].head(5).to_dict("records")
            raise ValueError(
                f"{int(tem_valor.sum())} linha(s) do arquivo de {tipo_operacao} têm CFOP vazio/inválido mas "
                f"parecem ser itens de verdade (têm valor preenchido) — confira o arquivo antes de importar. "
                f"Exemplos: {exemplos}"
            )
        df = df.loc[~cfop_vazio].reset_index(drop=True)

    out = pd.DataFrame({"produto_codigo": df["produto_codigo"].astype(str)})
    out["competencia_id"] = competencia_id
    out["empresa_id"] = empresa_id
    out["tipo_operacao"] = tipo_operacao
    out["ncm"] = df["ncm"].apply(lambda v: None if pd.isna(v) else str(int(v)) if float(v) == int(v) else str(v))
    out["cst"] = pd.to_numeric(df["cst"], errors="coerce").astype("Int64")
    out["cfop"] = df["cfop"].astype(int)
    out["quantidade"] = df["quantidade"].fillna(0).astype(float)
    out["valor_contabil"] = df["valor_contabil"].fillna(0).astype(float)
    out["valor_desconto"] = df["valor_desconto"].fillna(0).astype(float)
    out["valor_itens"] = df["valor_itens"].fillna(0).astype(float)
    out["valor_tributado"] = df["valor_tributado"].fillna(0).astype(float)
    out["aliq_pis"] = df["aliq_pis"].fillna(0).astype(float)
    out["valor_pis"] = df["valor_pis"].fillna(0).astype(float)
    out["aliq_cofins"] = df["aliq_cofins"].fillna(0).astype(float)
    out["valor_cofins"] = df["valor_cofins"].fillna(0).astype(float)
    out["valor_nao_tributado"] = df["valor_nao_tributado"].fillna(0).astype(float)

    if out["cst"].isna().any():
        n = int(out["cst"].isna().sum())
        raise ValueError(f"{n} linha(s) do arquivo de {tipo_operacao} têm CST vazio/inválido — confira o arquivo.")
    out["cst"] = out["cst"].astype(int)

    return out[COLS_TABELA]


def importar_arquivo(session, arquivo, tipo_operacao, competencia_id, empresa_id):
    df = _preparar_dataframe(arquivo, tipo_operacao, competencia_id, empresa_id)
    df.to_sql(
        "relatorio_pc_itens", session.bind, if_exists="append", index=False,
        method="multi", chunksize=500,
    )
    return len(df)


def _registrar_inconsistencias_1096(session, competencia_id, empresa_id):
    """CST fora da tabela oficial e CFOP sem grupo cadastrado, olhando só os itens desta filial (1096) —
    sinalizado, não ignorado. Desde a migração para o 1024 como fonte primária, isso serve só de conferência
    (não bloqueia o cálculo, que roda em cima de resumo_1024_pc). Escopado por empresa_id (filial): recria
    do zero só os achados desta filial, sem tocar nos de outras filiais da mesma competência (grupo)."""
    session.execute(text("""
        delete from inconsistencias_pc
        where competencia_id = :cid and empresa_id = :eid and fonte = 'relatorio_1096'
    """), {"cid": competencia_id, "eid": empresa_id})

    # Entrada do Lucro Presumido = só Devolução de Venda (sessão de continuação, 20/08/2026, "os outros não
    # precisa validar na presumido") — ver clausula_entrada_permitida_presumido em cst_regras_pc.py. Vazio
    # (sem filtro) para o Lucro Real, que continua 100% sem restrição nas duas direções.
    params_cst = {"cid": competencia_id, "eid": empresa_id}
    clausula_entrada_cst = clausula_entrada_permitida_presumido(session, competencia_id, "ri", params_cst)
    csts_ruins = session.execute(text(f"""
        select distinct ri.cst, ri.tipo_operacao
        from relatorio_pc_itens ri
        left join cst_pis_cofins c on c.codigo = ri.cst
        where ri.competencia_id = :cid and ri.empresa_id = :eid and c.codigo is null
          {clausula_entrada_cst}
    """), params_cst).mappings().all()
    for r in csts_ruins:
        session.execute(text("""
            insert into inconsistencias_pc (competencia_id, empresa_id, tipo, cst, tipo_operacao, descricao, fonte)
            values (:cid, :eid, 'cst_nao_mapeado', :cst, :tipo,
                    'CST ' || :cst || ' não consta na tabela oficial de PIS/COFINS — confira se é erro de '
                    || 'exportação do Winthor ou um código novo que precisa de cadastro manual.', 'relatorio_1096')
        """), {"cid": competencia_id, "eid": empresa_id, "cst": r["cst"], "tipo": r["tipo_operacao"]})

    params_cfop = {"cid": competencia_id, "eid": empresa_id}
    clausula_entrada_cfop = clausula_entrada_permitida_presumido(session, competencia_id, "ri", params_cfop)
    cfops_ruins = session.execute(text(f"""
        select distinct ri.cfop, ri.tipo_operacao
        from relatorio_pc_itens ri
        left join cfop_pis_cofins cp on cp.codigo = ri.cfop
        where ri.competencia_id = :cid and ri.empresa_id = :eid and cp.codigo is null
          {clausula_entrada_cfop}
    """), params_cfop).mappings().all()
    for r in cfops_ruins:
        session.execute(text("""
            insert into inconsistencias_pc (competencia_id, empresa_id, tipo, cfop, tipo_operacao, descricao, fonte)
            values (:cid, :eid, 'cfop_sem_grupo', :cfop, :tipo,
                    'CFOP ' || :cfop || ' (Relatório 1096) não está cadastrado em nenhum grupo da apuração '
                    || '— não entra na conferência com o 1024 para este CFOP até ser cadastrado em CFOP × '
                    || 'PIS/COFINS.', 'relatorio_1096')
        """), {"cid": competencia_id, "eid": empresa_id, "cfop": r["cfop"], "tipo": r["tipo_operacao"]})
    session.commit()


def importar_1096(session, empresa_id, competencia_id, arquivo_entrada=None, arquivo_saida=None, substituir=False):
    """Importa o Relatório 1096 (Entrada e/ou Saída) de UMA filial para dentro da competência do grupo já
    existente (ver get_or_create_competencia_grupo). Usado só para conferência com o 1024 e checagem de CST
    — não alimenta mais a apuração diretamente."""
    if not arquivo_entrada and not arquivo_saida:
        raise ValueError("Informe pelo menos um arquivo (Entrada e/ou Saída).")

    tipos = []
    if arquivo_entrada:
        tipos.append("entrada")
    if arquivo_saida:
        tipos.append("saida")
    removidos = checar_duplicacao(session, competencia_id, empresa_id, tipos, substituir)

    partes = []
    if removidos:
        partes.append(f"{removidos} itens antigos de {'/'.join(tipos)} removidos (substituição).")
    if arquivo_entrada:
        n = importar_arquivo(session, arquivo_entrada, "entrada", competencia_id, empresa_id)
        partes.append(f"Entrada: {n} itens importados.")
    if arquivo_saida:
        n = importar_arquivo(session, arquivo_saida, "saida", competencia_id, empresa_id)
        partes.append(f"Saída: {n} itens importados.")

    _registrar_inconsistencias_1096(session, competencia_id, empresa_id)
    registrar_inconsistencias_cst_regras(session, competencia_id, empresa_id)
    session.execute(text("update competencias set status = 'importada' where id = :cid"), {"cid": competencia_id})
    session.commit()
    return " ".join(partes)
