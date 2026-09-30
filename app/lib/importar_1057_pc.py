"""
Importação da Rotina 1057 do Winthor ("Relatório para Auditoria" Entrada/Saída) — 29/09/2026.

Para que serve: é a fonte do IPI da linha "6.3 (-) IPI" da apuração Lucro Real (só Entrada — o IPI só
existe do lado do crédito, decisão do usuário). A Saída é importada e guardada só para conferência.

Layout (aba 'Report', sem cabeçalho, .xls — a primeira linha vem vazia), confirmado com o cabeçalho
impresso do relatório enviado pelo usuário:

    Fornecedor | Nº Nota | Série | Dt.Emis. | Dt.Entr. | Produto | NCM | CFOP | Vl.Item | Vl.Desc. |
    Vl.Frete | Vl.Desp. | %IVA | % IPI | Vl. IPI | %ICMS | Base ICMS | Vl.ICMS | Base ST | Vl.ST |
    Vl.Total | UF | ST

Entrada = 23 colunas; Saída = 22 (sem "Dt.Entr."; "Fornecedor" vira o cliente). "Produto" vem como
"CÓDIGO - DESCRIÇÃO" — o código é separado para casar com `relatorio_pc_itens.produto_codigo`. Validado nos
dados reais de 08/2026 (Filial 6, 743 itens com IPI): Vl.Total = Vl.Item − Vl.Desc. + Vl.Frete + Vl.Desp. +
Vl. IPI em 100% dos itens, e Vl.Total = Valor Contábil do Relatório 1096.
"""
import re

import pandas as pd
from sqlalchemy import inspect as sa_inspect, text

from lib.competencia_status_pc import exigir_competencia_aberta
from lib.formatacao import formatar_moeda

COLS_ENTRADA = [
    "parceiro", "nota", "serie", "dt_emissao", "dt_entrada", "produto", "ncm", "cfop", "vl_item",
    "vl_desconto", "vl_frete", "vl_despesa", "pct_iva", "pct_ipi", "vl_ipi", "pct_icms", "base_icms",
    "vl_icms", "base_st", "vl_st", "vl_total", "uf", "cst_icms",
]
COLS_SAIDA = [c for c in COLS_ENTRADA if c != "dt_entrada"]

COLS_VALOR = [
    "vl_item", "vl_desconto", "vl_frete", "vl_despesa", "pct_iva", "pct_ipi", "vl_ipi", "pct_icms",
    "base_icms", "vl_icms", "base_st", "vl_st", "vl_total",
]
COLS_TABELA = [
    "competencia_id", "empresa_id", "tipo_operacao", "parceiro", "nota", "serie", "dt_emissao", "dt_entrada",
    "produto_codigo", "produto_descricao", "ncm", "cfop",
] + COLS_VALOR + ["uf", "cst_icms"]

_RE_PRODUTO = re.compile(r"^\s*(\d+)\s*-?\s*(.*)$")


def _texto_inteiro(v):
    """"1061.0"/1061 → "1061"; vazio → None. Usado pra nota/série/NCM (vêm como número no .xls)."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip()):
        return None
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(v).strip()
    except (TypeError, ValueError):
        return str(v).strip()


def _separar_produto(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None, None
    m = _RE_PRODUTO.match(str(v))
    if not m:
        return None, str(v).strip()
    return m.group(1), m.group(2).strip() or None


def preparar_dataframe(arquivo, tipo_operacao, competencia_id, empresa_id):
    """Lê o .xls da Rotina 1057 e devolve um DataFrame no formato de `relatorio_1057_pc`."""
    cols = COLS_ENTRADA if tipo_operacao == "entrada" else COLS_SAIDA
    # engine="calamine": lê .xls/.xlsx e tolera os arquivos "fora do padrão" que o Winthor gera (o .xls de
    # Saída de 08/2026 tem inconsistência OLE2 que o xlrd só aceita com aviso) — mesma escolha do 1096.
    df = pd.read_excel(arquivo, sheet_name="Report", header=None, engine="calamine")
    if len(df.columns) != len(cols):
        raise ValueError(
            f"Arquivo da Rotina 1057 de {tipo_operacao} tem {len(df.columns)} colunas, esperado {len(cols)} "
            f"(Entrada = 23, Saída = 22). Confira se é o 'Relatório para Auditoria' certo e se o arquivo de "
            f"Entrada/Saída não foi trocado."
        )
    df.columns = cols

    cfop = pd.to_numeric(df["cfop"], errors="coerce")
    vazio = cfop.isna()
    if vazio.any():
        tem_valor = vazio & (pd.to_numeric(df["vl_total"], errors="coerce").fillna(0) != 0)
        if tem_valor.any():
            exemplos = df.loc[tem_valor, ["nota", "produto", "vl_total"]].head(5).to_dict("records")
            raise ValueError(
                f"{int(tem_valor.sum())} linha(s) da Rotina 1057 de {tipo_operacao} têm CFOP vazio mas têm "
                f"valor — confira o arquivo antes de importar. Exemplos: {exemplos}"
            )
        df = df.loc[~vazio].reset_index(drop=True)
        cfop = cfop.loc[~vazio].reset_index(drop=True)

    produto = df["produto"].apply(_separar_produto)
    out = pd.DataFrame({
        "competencia_id": competencia_id,
        "empresa_id": empresa_id,
        "tipo_operacao": tipo_operacao,
        "parceiro": df["parceiro"].astype("object").where(df["parceiro"].notna(), None),
        "nota": df["nota"].apply(_texto_inteiro),
        "serie": df["serie"].apply(_texto_inteiro),
        "dt_emissao": pd.to_datetime(df["dt_emissao"], errors="coerce", dayfirst=True).dt.date,
        "dt_entrada": (pd.to_datetime(df["dt_entrada"], errors="coerce", dayfirst=True).dt.date
                       if "dt_entrada" in df.columns else None),
        "produto_codigo": produto.apply(lambda p: p[0]),
        "produto_descricao": produto.apply(lambda p: p[1]),
        "ncm": df["ncm"].apply(_texto_inteiro),
        "cfop": cfop.astype(int),
    })
    for c in COLS_VALOR:
        out[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(float)
    out["uf"] = df["uf"].astype("object").where(df["uf"].notna(), None)
    out["cst_icms"] = pd.to_numeric(df["cst_icms"], errors="coerce").astype("Int64")
    out["dt_emissao"] = out["dt_emissao"].astype("object").where(out["dt_emissao"].notna(), None)
    if tipo_operacao == "entrada":
        out["dt_entrada"] = out["dt_entrada"].astype("object").where(out["dt_entrada"].notna(), None)

    sem_produto = out["produto_codigo"].isna() & (out["vl_ipi"] != 0)
    if sem_produto.any():
        raise ValueError(
            f"{int(sem_produto.sum())} linha(s) com IPI têm a coluna Produto sem código no início (esperado "
            f"'CÓDIGO - DESCRIÇÃO') — sem o código não dá pra casar o IPI com o Relatório 1096."
        )
    return out[COLS_TABELA]


def contagem_por_filial(session, competencia_id):
    """{(empresa_id, tipo_operacao): n_itens} da Rotina 1057 nesta competência. Devolve None se a tabela
    ainda não existe (migração 016 não rodada) — a tela de importação mostra um aviso em vez de quebrar."""
    # via inspector, não SAVEPOINT: o engine de produção é AUTOCOMMIT (lib/db.py)
    if not sa_inspect(session.get_bind()).has_table("relatorio_1057_pc"):
        return None
    rows = session.execute(text("""
        select empresa_id, tipo_operacao, count(*) as n from relatorio_1057_pc
        where competencia_id = :cid group by empresa_id, tipo_operacao
    """), {"cid": competencia_id}).mappings().all()
    return {(r["empresa_id"], r["tipo_operacao"]): r["n"] for r in rows}


def contar_itens(session, competencia_id, empresa_id, tipo_operacao):
    return session.execute(text("""
        select count(*) from relatorio_1057_pc
        where competencia_id = :cid and empresa_id = :eid and tipo_operacao = :tipo
    """), {"cid": competencia_id, "eid": empresa_id, "tipo": tipo_operacao}).scalar() or 0


def importar_1057(session, empresa_id, competencia_id, arquivo_entrada=None, arquivo_saida=None,
                  substituir=False):
    """Importa a Rotina 1057 (Entrada e/ou Saída) de UMA filial para a competência do grupo. Escopado por
    filial + tipo: substituir a Entrada de uma filial não mexe na Saída nem nas outras filiais."""
    if not arquivo_entrada and not arquivo_saida:
        raise ValueError("Informe pelo menos um arquivo (Entrada e/ou Saída).")
    exigir_competencia_aberta(session, competencia_id)

    arquivos = []
    if arquivo_entrada:
        arquivos.append(("entrada", arquivo_entrada))
    if arquivo_saida:
        arquivos.append(("saida", arquivo_saida))

    # Lê e valida TUDO antes de apagar qualquer coisa — um arquivo com layout errado não pode deixar a
    # filial sem os dados antigos.
    preparados = [(tipo, preparar_dataframe(arq, tipo, competencia_id, empresa_id)) for tipo, arq in arquivos]

    partes = []
    for tipo, _ in preparados:
        n = contar_itens(session, competencia_id, empresa_id, tipo)
        if n and not substituir:
            raise ValueError(
                f"Esta filial já tem {n} itens da Rotina 1057 de {tipo} nesta competência. Marque "
                f"'substituir' se este é um relatório corrigido (evita duplicar)."
            )
        if n:
            session.execute(text("""
                delete from relatorio_1057_pc
                where competencia_id = :cid and empresa_id = :eid and tipo_operacao = :tipo
            """), {"cid": competencia_id, "eid": empresa_id, "tipo": tipo})
            partes.append(f"{n} itens antigos de {tipo} removidos (substituição).")

    for tipo, df in preparados:
        df.to_sql("relatorio_1057_pc", session.bind, if_exists="append", index=False,
                  method="multi", chunksize=500)
        ipi = df["vl_ipi"].sum()
        rotulo = "Entrada" if tipo == "entrada" else "Saída"
        partes.append(f"{rotulo}: {len(df)} itens importados (IPI total {formatar_moeda(ipi)}).")
    session.commit()
    return " ".join(partes)
