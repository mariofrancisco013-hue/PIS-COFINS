"""
Importação do "Relatório 1096" do Winthor ("Relatório por combinação de CFOP, CST, NCM e alíquota -
Analítico" — Entrada/Saída) para a tabela `relatorio_pc_itens`.

Mapeamento de colunas confirmado com o usuário em 14/08/2026 (print do cabeçalho do relatório original +
conferência aritmética: Vl.Tributado × %PIS/COFINS ÷ 100 = Vl.PIS/Vl.COFINS bateu em todas as linhas
testadas nos arquivos reais `1096 - Entradas.xlsx` / `1096 - saidas.xlsx`). Ver metodologia completa em
`claude/metodologia-pis-cofins-lucro-real.md` no projeto "PIS/COFINS".

IMPORTANTE: este export ("Report", sem cabeçalho, 14 colunas) NÃO traz o número da NF — só o relatório
impresso/agrupado por bloco de NF traz isso. Este módulo trabalha por item agregado (produto × NCM × CST ×
CFOP), sem granularidade de NF — ver nota na metodologia sobre por quê não há tela "por NF" neste módulo
(diferente do módulo ICMS Normal).
"""
import json

import pandas as pd
from sqlalchemy import text

COLS = [
    "produto_codigo", "ncm", "cst", "cfop", "quantidade", "valor_contabil", "valor_desconto",
    "valor_itens", "valor_tributado", "aliq_pis", "valor_pis", "aliq_cofins", "valor_cofins",
    "valor_nao_tributado",
]

COLS_TABELA = ["competencia_id", "tipo_operacao"] + COLS


def buscar_competencia(session, empresa_cnpj, ano, mes, modulo="pis_cofins_lucro_real"):
    """Só CONSULTA — devolve o id da competência se já existir, ou None. Não cria nada (mesmo motivo do
    módulo ICMS: navegar pelos filtros da tela não deve criar competência vazia no banco)."""
    empresa = session.execute(
        text("select id from empresas where cnpj = :cnpj"), {"cnpj": empresa_cnpj}
    ).fetchone()
    if not empresa:
        return None
    return session.execute(text("""
        select id from competencias where empresa_id=:eid and ano=:ano and mes=:mes and modulo=:modulo
    """), {"eid": empresa[0], "ano": ano, "mes": mes, "modulo": modulo}).scalar()


def get_or_create_competencia(session, empresa_cnpj, ano, mes, modulo="pis_cofins_lucro_real"):
    empresa = session.execute(
        text("select id from empresas where cnpj = :cnpj"), {"cnpj": empresa_cnpj}
    ).fetchone()
    if not empresa:
        raise ValueError(f"Empresa com CNPJ {empresa_cnpj} não encontrada.")
    empresa_id = empresa[0]

    comp = session.execute(text("""
        select id from competencias where empresa_id=:eid and ano=:ano and mes=:mes and modulo=:modulo
    """), {"eid": empresa_id, "ano": ano, "mes": mes, "modulo": modulo}).fetchone()
    if comp:
        return comp[0]

    result = session.execute(text("""
        insert into competencias (empresa_id, ano, mes, modulo, status)
        values (:eid, :ano, :mes, :modulo, 'aberta') returning id
    """), {"eid": empresa_id, "ano": ano, "mes": mes, "modulo": modulo})
    novo_id = result.fetchone()[0]
    session.commit()
    return novo_id


def checar_duplicacao(session, competencia_id, tipos, substituir):
    """Mesma lógica do módulo ICMS: checa/apaga só os tipos (entrada/saída) sendo reimportados agora, sem
    mexer no outro tipo já importado."""
    placeholders = ", ".join(f":t{i}" for i in range(len(tipos)))
    params = {f"t{i}": t for i, t in enumerate(tipos)}
    params["cid"] = competencia_id

    n = session.execute(
        text(f"select count(*) from relatorio_pc_itens where competencia_id = :cid "
             f"and tipo_operacao in ({placeholders})"),
        params,
    ).scalar()
    if n and not substituir:
        raise ValueError(
            f"Já existem {n} itens de {'/'.join(tipos)} importados para esta competência. Marque "
            f"'substituir' se este é um relatório corrigido (evita duplicar). Isso NÃO afeta o outro tipo "
            f"(Entrada/Saída) já importado para esta competência."
        )
    if n and substituir:
        session.execute(text("delete from inconsistencias_pc where competencia_id = :cid"), {"cid": competencia_id})
        session.execute(text("delete from apuracao_pc_linhas where competencia_id = :cid"), {"cid": competencia_id})
        session.execute(
            text(f"delete from relatorio_pc_itens where competencia_id = :cid "
                 f"and tipo_operacao in ({placeholders})"),
            params,
        )
        session.commit()
    return n or 0


def _preparar_dataframe(arquivo, tipo_operacao, competencia_id):
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

    # linhas de rodapé (ex.: "Total geral") vêm com CFOP vazio — descarta só essas; se sobrar alguma linha
    # com CFOP vazio mas com produto/valor preenchido, trava com erro explicando (mais seguro que gravar
    # um item sem CFOP ou adivinhar).
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


def importar_arquivo(session, arquivo, tipo_operacao, competencia_id):
    """`arquivo` pode ser um caminho (str/Path) ou um buffer tipo st.file_uploader."""
    df = _preparar_dataframe(arquivo, tipo_operacao, competencia_id)
    df.to_sql(
        "relatorio_pc_itens", session.bind, if_exists="append", index=False,
        method="multi", chunksize=500,
    )
    return len(df)


def _registrar_inconsistencias(session, competencia_id):
    """Sinaliza (não ignora) CST fora da tabela oficial e CFOP sem grupo cadastrado — ver metodologia no
    projeto sobre por que isso não pode ser adivinhado."""
    session.execute(text("delete from inconsistencias_pc where competencia_id = :cid and tipo in "
                          "('cst_nao_mapeado','cfop_sem_grupo')"), {"cid": competencia_id})

    csts_ruins = session.execute(text("""
        select distinct ri.cst, ri.tipo_operacao
        from relatorio_pc_itens ri
        left join cst_pis_cofins c on c.codigo = ri.cst
        where ri.competencia_id = :cid and c.codigo is null
    """), {"cid": competencia_id}).mappings().all()
    for r in csts_ruins:
        session.execute(text("""
            insert into inconsistencias_pc (competencia_id, tipo, cst, tipo_operacao, descricao)
            values (:cid, 'cst_nao_mapeado', :cst, :tipo,
                    'CST ' || :cst || ' não consta na tabela oficial de PIS/COFINS — confira se é erro de '
                    || 'exportação do Winthor ou um código novo que precisa de cadastro manual.')
        """), {"cid": competencia_id, "cst": r["cst"], "tipo": r["tipo_operacao"]})

    cfops_ruins = session.execute(text("""
        select distinct ri.cfop, ri.tipo_operacao
        from relatorio_pc_itens ri
        left join cfop_pis_cofins cp on cp.codigo = ri.cfop
        where ri.competencia_id = :cid and cp.codigo is null
    """), {"cid": competencia_id}).mappings().all()
    for r in cfops_ruins:
        session.execute(text("""
            insert into inconsistencias_pc (competencia_id, tipo, cfop, tipo_operacao, descricao)
            values (:cid, 'cfop_sem_grupo', :cfop, :tipo,
                    'CFOP ' || :cfop || ' não está cadastrado em nenhum grupo da apuração (1.1/1.2/1.4/1.6 '
                    || 'ou 5.1/5.2/5.5/5.7/5.8) — os itens desse CFOP ficam de fora do cálculo até ser '
                    || 'cadastrado em CFOP × PIS/COFINS.')
        """), {"cid": competencia_id, "cfop": r["cfop"], "tipo": r["tipo_operacao"]})
    session.commit()


def importar(session, empresa_cnpj, ano, mes, arquivo_entrada=None, arquivo_saida=None, substituir=False):
    """Fluxo completo: cria/acha a competência, checa duplicação, importa o(s) arquivo(s), sinaliza
    inconsistências de CST/CFOP e marca status."""
    if not arquivo_entrada and not arquivo_saida:
        raise ValueError("Informe pelo menos um arquivo (Entrada e/ou Saída).")

    competencia_id = get_or_create_competencia(session, empresa_cnpj, ano, mes)
    tipos = []
    if arquivo_entrada:
        tipos.append("entrada")
    if arquivo_saida:
        tipos.append("saida")
    removidos = checar_duplicacao(session, competencia_id, tipos, substituir)

    partes = []
    if removidos:
        partes.append(f"{removidos} itens antigos de {'/'.join(tipos)} removidos (substituição).")
    if arquivo_entrada:
        n = importar_arquivo(session, arquivo_entrada, "entrada", competencia_id)
        partes.append(f"Entrada: {n} itens importados.")
    if arquivo_saida:
        n = importar_arquivo(session, arquivo_saida, "saida", competencia_id)
        partes.append(f"Saída: {n} itens importados.")

    _registrar_inconsistencias(session, competencia_id)

    session.execute(text("update competencias set status = 'importada' where id = :cid"), {"cid": competencia_id})
    session.commit()
    partes.append(f"Competência {competencia_id} pronta para cálculo.")
    return " ".join(partes)
