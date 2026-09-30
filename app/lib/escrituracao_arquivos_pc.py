"""
Geração dos arquivos do relatório da escrituração (29/09/2026, migração 017): PDF com a memória de cálculo
explicada e Excel ANEXO com todas as tabelas e itens (pedido do usuário: "o Excel deve ser informado como
anexo" — o PDF cita o arquivo como Anexo e indica a aba de cada detalhe). Os dados vêm de
`escrituracao_pc.montar_escrituracao`.
"""
import io
import unicodedata
from decimal import Decimal
from xml.sax.saxutils import escape

ZERO = Decimal("0")


def nomes_arquivos(dados):
    m = dados["meta"]
    base = f"Escrituracao_PIS_COFINS_{m['cnpj_raiz']}_{m['ano']}-{int(m['mes']):02d}"
    if m.get("versao"):
        base += f"_v{m['versao']}"
    return base + ".pdf", base + "_Anexo.xlsx"


def _f(v):
    return float(v) if v is not None else None


def _br(v, casas=2):
    if v is None:
        return "—"
    v = Decimal(str(v))
    if v == 0:
        v = abs(v)  # evita "-0,00"
    s = f"{v:,.{casas}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def _data(dt):
    if dt is None:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except (AttributeError, ValueError):
        return str(dt)


# ================================================================================================== EXCEL
def gerar_xlsx(dados) -> bytes:
    import xlsxwriter

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False})
    base = {"font_name": "Arial", "font_size": 9}
    F = {
        "titulo": wb.add_format({**base, "bold": True, "font_size": 13}),
        "sub": wb.add_format({**base, "italic": True, "font_color": "#555555"}),
        "cab": wb.add_format({**base, "bold": True, "bg_color": "#1F3864", "font_color": "#FFFFFF", "border": 1,
                              "text_wrap": True, "valign": "vcenter"}),
        "txt": wb.add_format({**base}),
        "txtw": wb.add_format({**base, "text_wrap": True, "valign": "top"}),
        "neg": wb.add_format({**base, "bold": True}),
        "int": wb.add_format({**base, "num_format": "0"}),
        "moeda": wb.add_format({**base, "num_format": "#,##0.00;(#,##0.00);-"}),
        "moeda_neg": wb.add_format({**base, "bold": True, "num_format": "#,##0.00;(#,##0.00);-", "top": 1}),
        "pct": wb.add_format({**base, "num_format": "0.0000%"}),
        "ok": wb.add_format({**base, "font_color": "#006100", "bg_color": "#C6EFCE"}),
        "erro": wb.add_format({**base, "font_color": "#9C0006", "bg_color": "#FFC7CE"}),
        "total_lbl": wb.add_format({**base, "bold": True, "top": 1}),
    }
    m = dados["meta"]
    nome_pdf, _ = nomes_arquivos(dados)

    def tabela(nome, titulo, colunas, linhas, total_cols=(), larguras=None, nota=None):
        """colunas = [(cabeçalho, chave, formato)]. Linha de total com SUBTOTAL (respeita filtro)."""
        ws = wb.add_worksheet(nome)
        ws.write(0, 0, titulo, F["titulo"])
        ws.write(1, 0, f"{m['nome_grupo']} — CNPJ raiz {m['cnpj_raiz']} — competência {m['periodo']}. "
                       f"Anexo do relatório {nome_pdf}." + (f" {nota}" if nota else ""), F["sub"])
        lin0 = 3
        for j, (cab, _k, _fmt) in enumerate(colunas):
            ws.write(lin0, j, cab, F["cab"])
        for i, row in enumerate(linhas, start=lin0 + 1):
            for j, (_cab, k, fmt) in enumerate(colunas):
                v = row.get(k) if isinstance(row, dict) else row[j]
                if v is None or v == "":
                    ws.write_blank(i, j, None, F[fmt] if fmt in F else F["txt"])
                elif fmt in ("moeda", "pct"):
                    ws.write_number(i, j, float(v), F[fmt])
                elif fmt == "int":
                    ws.write_number(i, j, int(v), F["int"])
                else:
                    ws.write(i, j, str(v) if not isinstance(v, (int, float)) else v, F[fmt] if fmt in F else F["txt"])
        ult = lin0 + len(linhas)
        if total_cols and linhas:
            ws.write(ult + 1, 0, "Total", F["total_lbl"])
            for j, (_cab, k, _fmt) in enumerate(colunas):
                if k in total_cols:
                    col = xlsxwriter.utility.xl_col_to_name(j)
                    ws.write_formula(ult + 1, j, f"=SUBTOTAL(9,{col}{lin0 + 2}:{col}{ult + 1})", F["moeda_neg"])
        ws.freeze_panes(lin0 + 1, 0)
        if linhas:
            ws.autofilter(lin0, 0, ult, len(colunas) - 1)
        for j, larg in enumerate(larguras or [14] * len(colunas)):
            ws.set_column(j, j, larg)
        return ws

    # ---- Leia-me
    ws = wb.add_worksheet("Leia-me")
    ws.set_column(0, 0, 28)
    ws.set_column(1, 1, 110)
    ws.write(0, 0, "Anexo — Memória de cálculo PIS/COFINS (Lucro Real, não cumulativo)", F["titulo"])
    info = [
        ("Relatório principal", nome_pdf),
        ("Grupo", f"{m['nome_grupo']} — CNPJ raiz {m['cnpj_raiz']}"),
        ("Competência", m["periodo"]),
        ("Filiais", "; ".join(f["rotulo"] for f in m["filiais"])),
        ("Versão da escrituração", str(m.get("versao") or "—")),
        ("Gerado em", _data(m["gerado_em"])),
        ("Gerado por", m.get("gerado_por") or "—"),
        ("DARF PIS", _br(dados["darf"]["darf_pis"])),
        ("DARF COFINS", _br(dados["darf"]["darf_cofins"])),
    ]
    for i, (k, v) in enumerate(info, start=2):
        ws.write(i, 0, k, F["neg"])
        ws.write(i, 1, v, F["txt"])
    i = len(info) + 3
    ws.write(i, 0, "Aba", F["cab"])
    ws.write(i, 1, "Conteúdo", F["cab"])
    for nome, desc in dados["abas_anexo"]:
        i += 1
        ws.write_url(i, 0, f"internal:'{nome}'!A1", string=nome)
        ws.write(i, 1, desc, F["txt"])

    # ---- Resumo DARF (fórmulas)
    ws = wb.add_worksheet("Resumo DARF")
    ws.set_column(0, 0, 62)
    ws.set_column(1, 3, 16)
    ws.write(0, 0, f"Composição do DARF — competência {m['periodo']}", F["titulo"])
    ws.write(1, 0, "Valores de entrada = linhas gravadas da apuração (aba Apuração). Débito, crédito e saldo "
                   "são fórmulas.", F["sub"])
    for j, cab in enumerate(["Item", "Linha", "PIS", "COFINS"]):
        ws.write(3, j, cab, F["cab"])
    lin = 4
    refs = {"Débito": [], "Crédito": []}
    for x in dados["darf"]["composicao"]:
        ws.write(lin, 0, x["descricao"], F["txt"])
        ws.write(lin, 1, x["linha"], F["txt"])
        ws.write_number(lin, 2, float(x["pis"] * x["sinal"]), F["moeda"])
        ws.write_number(lin, 3, float(x["cofins"] * x["sinal"]), F["moeda"])
        refs[x["grupo"]].append(lin + 1)
        lin += 1
    lin += 1

    def soma(col, linhas_):
        return "=" + "+".join(f"{col}{r}" for r in linhas_) if linhas_ else "=0"

    ws.write(lin, 0, "Débito total (1 − 2.4 − 2.6 + 3 + 4)", F["neg"])
    ws.write_formula(lin, 2, soma("C", refs["Débito"]), F["moeda_neg"], float(dados["darf"]["debito_pis"]))
    ws.write_formula(lin, 3, soma("D", refs["Débito"]), F["moeda_neg"], float(dados["darf"]["debito_cofins"]))
    l_deb = lin + 1
    lin += 1
    ws.write(lin, 0, "Crédito total (5 − 6.6)", F["neg"])
    ws.write_formula(lin, 2, soma("C", refs["Crédito"]), F["moeda_neg"], float(dados["darf"]["credito_pis"]))
    ws.write_formula(lin, 3, soma("D", refs["Crédito"]), F["moeda_neg"], float(dados["darf"]["credito_cofins"]))
    l_cred = lin + 1
    lin += 1
    ws.write(lin, 0, "Saldo credor do período anterior (8.1 / 8.2)", F["txt"])
    ws.write_number(lin, 2, float(dados["darf"]["saldo_anterior_pis"]), F["moeda"])
    ws.write_number(lin, 3, float(dados["darf"]["saldo_anterior_cofins"]), F["moeda"])
    l_ant = lin + 1
    lin += 1
    ws.write(lin, 0, "Saldo = débito − crédito − saldo anterior", F["neg"])
    ws.write_formula(lin, 2, f"=C{l_deb}-C{l_cred}-C{l_ant}", F["moeda_neg"], float(dados["darf"]["saldo_pis"]))
    ws.write_formula(lin, 3, f"=D{l_deb}-D{l_cred}-D{l_ant}", F["moeda_neg"], float(dados["darf"]["saldo_cofins"]))
    l_saldo = lin + 1
    lin += 1
    ws.write(lin, 0, "DARF calculado (saldo, quando positivo)", F["neg"])
    ws.write_formula(lin, 2, f"=MAX(C{l_saldo},0)", F["moeda_neg"], float(max(dados["darf"]["saldo_pis"], ZERO)))
    ws.write_formula(lin, 3, f"=MAX(D{l_saldo},0)", F["moeda_neg"], float(max(dados["darf"]["saldo_cofins"], ZERO)))
    l_calc = lin + 1
    lin += 1
    ws.write(lin, 0, "DARF gravado na apuração (11.1 / 11.2)", F["neg"])
    ws.write_number(lin, 2, float(dados["darf"]["darf_pis"]), F["moeda_neg"])
    ws.write_number(lin, 3, float(dados["darf"]["darf_cofins"]), F["moeda_neg"])
    l_grav = lin + 1
    lin += 1
    ws.write(lin, 0, "Diferença (deve ser zero)", F["txt"])
    ws.write_formula(lin, 2, f"=C{l_calc}-C{l_grav}", F["moeda"], 0)
    ws.write_formula(lin, 3, f"=D{l_calc}-D{l_grav}", F["moeda"], 0)
    lin += 2
    ws.write(lin, 0, "Total do DARF (PIS + COFINS)", F["neg"])
    ws.write_formula(lin, 2, f"=C{l_grav}+D{l_grav}", F["moeda_neg"], float(dados["darf"]["darf_total"]))

    # ---- Apuração
    tabela("Apuração", "Apuração PIS/COFINS — linhas", [
        ("Seção", "secao", "txt"), ("Linha", "linha", "txt"), ("Descrição", "descricao", "txt"),
        ("Base", "base", "moeda"), ("Base líquida", "base_liquida", "moeda"), ("PIS", "pis", "moeda"),
        ("COFINS", "cofins", "moeda"), ("Observação", "observacao", "txtw"),
    ], dados["linhas"], larguras=[30, 7, 60, 16, 16, 14, 14, 70])

    col_deb = [("Grupo", "grupo", "txt"), ("Descrição do grupo", "grupo_desc", "txt"), ("CFOP", "cfop", "int"),
               ("Descrição do CFOP", "descricao", "txt"), ("Fonte do valor", "fonte", "txt"),
               ("Valor Contábil", "contabil", "moeda"), ("(-) ICMS [2.3]", "icms", "moeda"),
               ("(-) CST 6/7 [2.7]", "cst", "moeda"), ("(-) Outras [2.5]", "outras", "moeda"),
               ("Base líquida", "liquido", "moeda"), ("PIS", "pis", "moeda"), ("COFINS", "cofins", "moeda")]
    tabela("Consolidação Débito", "Saídas — consolidação por grupo e CFOP", col_deb, dados["consolidacao"]["saida"],
           total_cols={"contabil", "icms", "cst", "outras", "liquido", "pis", "cofins"},
           larguras=[7, 28, 7, 40, 24, 16, 15, 15, 15, 16, 13, 13],
           nota="PIS/COFINS por CFOP são informativos (a apuração arredonda por grupo).")
    col_cred = [("Grupo", "grupo", "txt"), ("Descrição do grupo", "grupo_desc", "txt"), ("CFOP", "cfop", "int"),
                ("Descrição do CFOP", "descricao", "txt"), ("Fonte do valor", "fonte", "txt"),
                ("Valor Contábil", "contabil", "moeda"), ("(-) IPI [6.3]", "ipi", "moeda"),
                ("(-) ICMS [6.4]", "icms", "moeda"), ("(-) CST s/ crédito [6.5]", "cst", "moeda"),
                ("(-) Outras [6.7]", "outras", "moeda"), ("Base líquida", "liquido", "moeda"),
                ("PIS", "pis", "moeda"), ("COFINS", "cofins", "moeda")]
    tabela("Consolidação Crédito", "Entradas — consolidação por grupo e CFOP", col_cred,
           dados["consolidacao"]["entrada"],
           total_cols={"contabil", "ipi", "icms", "cst", "outras", "liquido", "pis", "cofins"},
           larguras=[7, 28, 7, 40, 24, 16, 14, 15, 15, 15, 16, 13, 13],
           nota="PIS/COFINS por CFOP são informativos (a apuração arredonda por grupo).")
    tabela("CFOP x CST", "Itens do Relatório 1096 por CFOP e CST", [
        ("Direção", "tipo", "txt"), ("Grupo", "grupo", "txt"), ("CFOP", "cfop", "int"), ("CST", "cst", "int"),
        ("Linha da apuração", "linha", "txt"), ("Itens", "n", "int"), ("Valor Contábil", "contabil", "moeda"),
        ("Valor Tributado", "tributado", "moeda"), ("Valor Não Tributado", "nao_tributado", "moeda"),
        ("IPI (1057)", "ipi", "moeda"), ("Valor na linha", "valor_linha", "moeda"), ("IPI na 6.3", "ipi_6_3", "moeda"),
    ], dados["cfop_cst"], total_cols={"contabil", "tributado", "nao_tributado", "ipi", "valor_linha", "ipi_6_3"},
        larguras=[9, 7, 7, 6, 26, 7, 16, 16, 16, 13, 16, 13])
    tabela("Itens Saída", "Itens do Relatório 1096 — saída", [
        ("Filial", "filial", "txt"), ("Produto", "produto", "txt"), ("NCM", "ncm", "txt"), ("CST", "cst", "int"),
        ("CFOP", "cfop", "int"), ("Grupo", "grupo", "txt"), ("Valor Contábil", "contabil", "moeda"),
        ("Valor Tributado", "tributado", "moeda"), ("Valor Não Tributado", "nao_tributado", "moeda"),
        ("Linha da apuração", "linha", "txt"), ("Valor na linha", "valor_linha", "moeda"),
        ("Base líquida do item", "base_liquida", "moeda"), ("Observação", "obs", "txt"),
    ], dados["itens"]["saida"], total_cols={"contabil", "tributado", "nao_tributado", "valor_linha", "base_liquida"},
        larguras=[30, 10, 10, 6, 7, 7, 15, 15, 15, 20, 15, 15, 60])
    tabela("Itens Entrada", "Itens do Relatório 1096 — entrada (com IPI da Rotina 1057)", [
        ("Filial", "filial", "txt"), ("Produto", "produto", "txt"), ("NCM", "ncm", "txt"), ("CST", "cst", "int"),
        ("CFOP", "cfop", "int"), ("Grupo", "grupo", "txt"), ("Valor Contábil", "contabil", "moeda"),
        ("Valor Tributado", "tributado", "moeda"), ("Valor Não Tributado", "nao_tributado", "moeda"),
        ("IPI (1057)", "ipi", "moeda"), ("Linha da apuração", "linha", "txt"), ("Valor na linha", "valor_linha", "moeda"),
        ("IPI na 6.3", "ipi_6_3", "moeda"), ("Base líquida do item", "base_liquida", "moeda"),
        ("Observação", "obs", "txt"),
    ], dados["itens"]["entrada"],
        total_cols={"contabil", "tributado", "nao_tributado", "ipi", "valor_linha", "ipi_6_3", "base_liquida"},
        larguras=[30, 10, 10, 6, 7, 7, 15, 15, 15, 13, 20, 15, 13, 15, 60])
    tabela("IPI Rotina 1057", "Itens da Rotina 1057 com IPI e o casamento com o Relatório 1096", [
        ("Filial", "filial", "txt"), ("Nota", "nota", "txt"), ("Série", "serie", "txt"),
        ("Fornecedor", "fornecedor", "txt"), ("Produto", "produto", "txt"), ("Descrição", "descricao", "txt"),
        ("NCM", "ncm", "txt"), ("CFOP", "cfop", "int"), ("Vl. Total", "vl_total", "moeda"), ("Vl. IPI", "vl_ipi", "moeda"),
        ("Casamento com o 1096", "casamento", "txt"), ("CST no 1096", "cst_1096", "int"),
    ], dados["ipi_1057"], total_cols={"vl_total", "vl_ipi"},
        larguras=[30, 10, 6, 36, 10, 40, 10, 7, 15, 13, 30, 10])
    tabela("LC 224", "Linha 4 — Produtos isentos com incidência residual (LC 224/2025), por NCM", [
        ("NCM", "ncm", "txt"), ("Base (valor não tributado)", "base", "moeda"), ("Alíquota PIS", "aliq_pis", "pct"),
        ("Alíquota COFINS", "aliq_cofins", "pct"), ("PIS", "pis", "moeda"), ("COFINS", "cofins", "moeda"),
    ], dados["lc224"], total_cols={"base", "pis", "cofins"}, larguras=[12, 20, 13, 13, 14, 14],
        nota="PIS/COFINS por NCM sem arredondamento; a linha 4 arredonda o total.")

    ws = tabela("Lançamentos", "Lançamentos manuais", [
        ("Linha", "linha", "txt"), ("Tipo", "tipo", "txt"), ("Descrição", "descricao", "txt"), ("Base", "base", "moeda"),
        ("PIS", "pis", "moeda"), ("COFINS", "cofins", "moeda"), ("Situação", "situacao", "txt"),
    ], dados["lancamentos"], larguras=[7, 50, 36, 15, 13, 13, 44])
    lin = 6 + len(dados["lancamentos"])
    ws.write(lin, 0, "Receitas Financeiras (linha 3)", F["neg"])
    for i, r in enumerate(dados["receitas_financeiras"], start=lin + 1):
        ws.write(i, 1, r["subitem"], F["txt"])
        ws.write_number(i, 3, float(r["valor"]), F["moeda"])
    lin = lin + 2 + len(dados["receitas_financeiras"])
    ws.write(lin, 0, "Saldo credor anterior (8.1 / 8.2)", F["neg"])
    ws.write(lin + 1, 1, "PIS", F["txt"])
    ws.write_number(lin + 1, 3, float(dados["darf"]["saldo_anterior_pis"]), F["moeda"])
    ws.write(lin + 2, 1, "COFINS", F["txt"])
    ws.write_number(lin + 2, 3, float(dados["darf"]["saldo_anterior_cofins"]), F["moeda"])

    tabela("Rotina 1024", "Rotina 1024 (Livro RAICMS) por filial e CFOP", [
        ("Filial", "filial", "txt"), ("Direção", "tipo", "txt"), ("CFOP", "cfop", "int"), ("Descrição", "descricao", "txt"),
        ("Grupo", "grupo", "txt"), ("Valor Contábil", "contabil", "moeda"), ("ICMS", "icms", "moeda"),
    ], dados["rotina_1024"], total_cols={"contabil", "icms"}, larguras=[30, 9, 7, 44, 7, 16, 14])
    conf = [{k: (v if not isinstance(v, Decimal) else v) for k, v in r.items()} for r in dados["conferencia_1024_1096"]]
    tabela("Conferência 1024x1096", "Conferência por CFOP: Rotina 1024 × Relatório 1096", [
        ("CFOP", "cfop", "int"), ("Direção", "tipo_operacao", "txt"), ("PIS 1024", "pis_1024", "moeda"),
        ("COFINS 1024", "cofins_1024", "moeda"), ("PIS 1096", "pis_1096", "moeda"), ("COFINS 1096", "cofins_1096", "moeda"),
        ("Dif. PIS", "diff_pis", "moeda"), ("Dif. COFINS", "diff_cofins", "moeda"), ("Situação", "situacao", "txt"),
        ("ICMS 1024", "icms_1024", "moeda"), ("ICMS 1096", "icms_1096", "moeda"), ("Situação ICMS", "situacao_icms", "txt"),
    ], conf, larguras=[7, 9, 13, 13, 13, 13, 12, 12, 40, 13, 13, 36])

    ws = tabela("Conferências", "Checagens de consistência do cálculo", [
        ("Checagem", "descricao", "txt"), ("Esperado", "esperado", "moeda"), ("Obtido", "obtido", "moeda"),
        ("Diferença", "diferenca", "moeda"), ("Resultado", "resultado", "txt"), ("Explicação", "explicacao", "txtw"),
    ], dados["conferencias"],
        larguras=[70, 16, 16, 13, 11, 70])
    for i, c in enumerate(dados["conferencias"], start=4):
        ws.write(i, 4, c["resultado"], F["ok"] if c["ok"] else F["erro"])

    tabela("Inconsistências", "Inconsistências de cadastro pendentes no encerramento", [
        ("Tipo", "tipo", "txt"), ("Direção", "tipo_operacao", "txt"), ("Filial", "filial_winthor", "txt"),
        ("CFOP", "cfop", "int"), ("CST", "cst", "int"), ("Descrição", "descricao", "txtw"),
    ], dados["inconsistencias"], larguras=[18, 9, 8, 7, 6, 100])

    ws = wb.add_worksheet("Metodologia")
    ws.set_column(0, 0, 30)
    ws.set_column(1, 1, 120)
    ws.write(0, 0, "Metodologia do cálculo", F["titulo"])
    for i, (tit, txt) in enumerate(dados["metodologia"], start=2):
        ws.write(i, 0, tit, F["neg"])
        ws.write(i, 1, txt, F["txtw"])
        ws.set_row(i, 15 * (len(txt) // 110 + 1))
    wb.close()
    return buf.getvalue()


# ================================================================================================== PDF
_TROCAS = {"−": "-", "–": "-", "→": "->", "←": "<-", "≠": "<>", "≤": "<=", "≥": ">=", "✅": "", "⏳": "",
           "ℹ️": "", "ℹ": "", "​": "", "\xa0": " "}


def _pdf_txt(s):
    """Texto seguro para as fontes padrão do PDF (WinAnsi/cp1252): troca símbolos sem glifo (ex.: o sinal de
    menos Unicode "−" viraria um quadrado preto) e descarta o que não existir na codificação."""
    if s is None:
        return ""
    s = str(s)
    for a, b in _TROCAS.items():
        s = s.replace(a, b)
    s = unicodedata.normalize("NFC", s)
    return s.encode("cp1252", errors="ignore").decode("cp1252")


def gerar_pdf(dados, nome_anexo) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    m = dados["meta"]
    d = dados["darf"]
    ss = getSampleStyleSheet()
    AZUL = colors.HexColor("#1F3864")
    st = {
        "tit": ParagraphStyle("tit", parent=ss["Title"], fontSize=16, leading=20, textColor=AZUL, spaceAfter=4),
        "h1": ParagraphStyle("h1", parent=ss["Heading2"], fontSize=12.5, leading=15, textColor=AZUL,
                             spaceBefore=10, spaceAfter=4, keepWithNext=1),
        "h2": ParagraphStyle("h2", parent=ss["Heading3"], fontSize=10.5, leading=13, spaceBefore=6, spaceAfter=2,
                             keepWithNext=1),
        "p": ParagraphStyle("p", parent=ss["BodyText"], fontSize=8.8, leading=11.5, spaceAfter=4),
        "pi": ParagraphStyle("pi", parent=ss["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#444444")),
        "cel": ParagraphStyle("cel", parent=ss["BodyText"], fontSize=7.2, leading=8.6),
        "celb": ParagraphStyle("celb", parent=ss["BodyText"], fontSize=7.2, leading=8.6, fontName="Helvetica-Bold"),
        "cab": ParagraphStyle("cab", parent=ss["BodyText"], fontSize=7.2, leading=8.6, fontName="Helvetica-Bold",
                              textColor=colors.white),
        "cabr": ParagraphStyle("cabr", parent=ss["BodyText"], fontSize=7.2, leading=8.6, fontName="Helvetica-Bold",
                               textColor=colors.white, alignment=TA_RIGHT),
        "num": ParagraphStyle("num", parent=ss["BodyText"], fontSize=7.2, leading=8.6, alignment=TA_RIGHT),
        "numb": ParagraphStyle("numb", parent=ss["BodyText"], fontSize=7.2, leading=8.6, alignment=TA_RIGHT,
                               fontName="Helvetica-Bold"),
        "obs": ParagraphStyle("obs", parent=ss["BodyText"], fontSize=6.6, leading=8, textColor=colors.HexColor("#555555"),
                              fontName="Helvetica-Oblique"),
    }

    def P(txt, estilo="p"):
        return Paragraph(escape(_pdf_txt(txt)).replace("\n", "<br/>"), st[estilo])

    def anexo(aba):
        return P(f"Detalhe no Anexo ({nome_anexo}), aba \"{aba}\".", "pi")

    def grade(cabecalho, linhas, larguras, numericas=(), negrito=None, repetir=1):
        dados_t = [[P(c, "cabr" if j in numericas else "cab") for j, c in enumerate(cabecalho)]]
        estilos = []
        for i, row in enumerate(linhas, start=1):
            b = negrito(row) if negrito else False
            cel = []
            for j, v in enumerate(row["valores"] if isinstance(row, dict) else row):
                if j in numericas:
                    cel.append(P(v, "numb" if b else "num"))
                else:
                    cel.append(P(v, "celb" if b else "cel"))
            dados_t.append(cel)
            if b:
                estilos.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#E8EEF7")))
            if isinstance(row, dict) and row.get("obs"):
                dados_t.append([P(row["obs"], "obs")] + [""] * (len(cabecalho) - 1))
                estilos.append(("SPAN", (0, len(dados_t) - 1), (-1, len(dados_t) - 1)))
        t = Table(dados_t, colWidths=larguras, repeatRows=repetir)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C2D1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ] + estilos))
        return t

    buf = io.BytesIO()
    pagina = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=pagina, leftMargin=1.3 * cm, rightMargin=1.3 * cm, topMargin=1.3 * cm,
                            bottomMargin=1.4 * cm,
                            title=_pdf_txt(f"Escrituração PIS/COFINS {m['periodo']} — {m['nome_grupo']}"),
                            author=_pdf_txt(m.get("gerado_por") or ""), subject="Apuração PIS/COFINS não cumulativo")
    largura = pagina[0] - 2.6 * cm

    def rodape(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(1.3 * cm, 0.8 * cm, _pdf_txt(
            f"{m['nome_grupo']} — CNPJ raiz {m['cnpj_raiz']} — Escrituração PIS/COFINS {m['periodo']}"
            f"{' — versão ' + str(m['versao']) if m.get('versao') else ''} — Anexo: {nome_anexo}"))
        canvas.drawRightString(pagina[0] - 1.3 * cm, 0.8 * cm, f"Página {doc_.page}")
        canvas.restoreState()

    s = []
    # ---- capa / identificação
    s.append(P("Relatório da Escrituração — PIS/COFINS Não Cumulativo (Lucro Real)", "tit"))
    ident = [
        ["Grupo", f"{m['nome_grupo']} — CNPJ raiz {m['cnpj_raiz']}"],
        ["Competência", m["periodo"]],
        ["Filiais consolidadas", "; ".join(f"{f['rotulo']} ({f['cnpj']})" for f in m["filiais"])],
        ["Situação", f"Competência encerrada — versão {m.get('versao') or '—'}, gerada em {_data(m['gerado_em'])}"
                     f" por {m.get('gerado_por') or '—'}. Apuração calculada em {_data(m.get('calculado_em'))}."],
        ["Anexo", f"{nome_anexo} — planilha com todas as tabelas de consolidação e os itens (ver seção 11)."],
    ]
    t = Table([[P(a, "celb"), P(b, "cel")] for a, b in ident], colWidths=[4 * cm, largura - 4 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C2D1")),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8EEF7")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    s += [t, Spacer(1, 8)]

    # ---- 1. resultado
    s.append(P("1. Resultado — valores do DARF", "h1"))
    t = Table([[P("", "celb"), P("PIS", "numb"), P("COFINS", "numb"), P("Total", "numb")],
               [P("Líquido a pagar em DARF", "celb"), P(_br(d["darf_pis"]), "numb"), P(_br(d["darf_cofins"]), "numb"),
                P(_br(d["darf_total"]), "numb")]], colWidths=[8 * cm, 4 * cm, 4 * cm, 4 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C2D1")),
                           ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#FFF2CC"))]))
    s += [t, Spacer(1, 6), P("Composição (valores das linhas da apuração):", "h2")]
    comp = []
    for x in d["composicao"]:
        sinal = "(−) " if x["sinal"] < 0 else ""
        comp.append([x["grupo"], sinal + x["descricao"], _br(x["pis"] * x["sinal"]), _br(x["cofins"] * x["sinal"])])
    comp += [
        {"valores": ["Débito", "Débito total (1 − 2.4 − 2.6 + 3 + 4)", _br(d["debito_pis"]), _br(d["debito_cofins"])], "b": 1},
        {"valores": ["Crédito", "Crédito total (5 − 6.6)", _br(d["credito_pis"]), _br(d["credito_cofins"])], "b": 1},
        ["Saldo anterior", "(−) Saldo credor do período anterior (8.1 / 8.2)", _br(-d["saldo_anterior_pis"]),
         _br(-d["saldo_anterior_cofins"])],
        {"valores": ["Resultado", "Saldo = débito − crédito − saldo anterior", _br(d["saldo_pis"]), _br(d["saldo_cofins"])], "b": 1},
        {"valores": ["DARF", "Líquido a pagar (saldo, quando positivo) — linhas 11.1 / 11.2", _br(d["darf_pis"]),
                     _br(d["darf_cofins"])], "b": 1},
    ]
    s += [grade(["Bloco", "Item", "PIS", "COFINS"], comp, [3 * cm, largura - 11 * cm, 4 * cm, 4 * cm], numericas=(2, 3),
                negrito=lambda r: isinstance(r, dict) and r.get("b")), anexo("Resumo DARF")]

    if dados["avisos"]:
        s.append(P("Pontos de atenção no encerramento:", "h2"))
        for a in dados["avisos"]:
            s.append(P("• " + a))

    # ---- 2. metodologia
    s.append(P("2. Fontes de dados e metodologia", "h1"))
    for tit, txt in dados["metodologia"]:
        s.append(KeepTogether([P(tit, "h2"), P(txt)]))

    # ---- 3. apuração
    s += [PageBreak(), P("3. Apuração linha a linha", "h1"),
          P("Base = valor da linha (nos grupos de CFOP, o Valor Contábil bruto); Base líquida = o que multiplica a "
            "alíquota. Nas linhas de exclusão, PIS/COFINS mostram quanto aquela exclusão representa (já embutido nos "
            "totais 1 e 5).", "pi")]
    rows = []
    for l in dados["linhas"]:
        rows.append({"valores": [l["linha"], l["descricao"], _br(l["base"]) if l["base"] is not None else "—",
                                 _br(l["base_liquida"]) if l["base_liquida"] is not None else "—",
                                 _br(l["pis"]), _br(l["cofins"])],
                     "b": l["nivel"] == 0, "obs": l.get("observacao")})
    s += [grade(["Linha", "Descrição", "Base", "Base líquida", "PIS", "COFINS"], rows,
                [1.4 * cm, largura - 15.4 * cm, 3.6 * cm, 3.6 * cm, 3.4 * cm, 3.4 * cm], numericas=(2, 3, 4, 5),
                negrito=lambda r: r.get("b")), anexo("Apuração")]

    # ---- 4/5. consolidação
    def consolidado(tipo, titulo, cols, aba):
        linhas_c = dados["consolidacao"][tipo]
        out = [PageBreak(), P(titulo, "h1")]
        rows_ = []
        totais = {k: ZERO for _c, k in cols if k}
        grupo_atual = None
        for c in linhas_c:
            if c["grupo"] != grupo_atual:
                grupo_atual = c["grupo"]
                sub = [x for x in linhas_c if x["grupo"] == grupo_atual]
                rows_.append({"valores": [grupo_atual, "", c["grupo_desc"]] +
                              [_br(sum((x[k] for x in sub), ZERO)) for _c, k in cols if k], "b": 1})
            rows_.append({"valores": ["", str(c["cfop"]), c.get("descricao") or ""] +
                          [_br(c[k]) for _c, k in cols if k]})
            for _c, k in cols:
                if k:
                    totais[k] += c[k]
        rows_.append({"valores": ["Total", "", ""] + [_br(totais[k]) for _c, k in cols if k], "b": 1})
        n = len([k for _c, k in cols if k])
        larg_num = 2.55 * cm
        out.append(grade(["Grupo", "CFOP", "Descrição"] + [c for c, k in cols if k], rows_,
                         [1.2 * cm, 1.4 * cm, largura - 2.6 * cm - n * larg_num] + [larg_num] * n,
                         numericas=tuple(range(3, 3 + n)), negrito=lambda r: r.get("b")))
        out.append(anexo(aba))
        return out

    s += consolidado("saida", "4. Débito — consolidação por grupo e CFOP de saída", [
        ("Valor Contábil", "contabil"), ("(-) ICMS [2.3]", "icms"), ("(-) CST 6/7 [2.7]", "cst"),
        ("(-) Outras [2.5]", "outras"), ("Base líquida", "liquido"), ("PIS", "pis"), ("COFINS", "cofins")],
        "Consolidação Débito")
    s.append(P("Itens do Relatório 1096 de saída, com a linha da apuração de cada um: Anexo, aba \"Itens Saída\"; "
               "resumo por CFOP e CST: aba \"CFOP x CST\".", "pi"))
    s += consolidado("entrada", "5. Crédito — consolidação por grupo e CFOP de entrada", [
        ("Valor Contábil", "contabil"), ("(-) IPI [6.3]", "ipi"), ("(-) ICMS [6.4]", "icms"),
        ("(-) CST s/créd. [6.5]", "cst"), ("(-) Outras [6.7]", "outras"), ("Base líquida", "liquido"),
        ("PIS", "pis"), ("COFINS", "cofins")], "Consolidação Crédito")
    s.append(P("Itens do Relatório 1096 de entrada, com o IPI casado e a linha de cada um: Anexo, aba \"Itens "
               "Entrada\".", "pi"))

    # ---- 6. IPI
    s += [PageBreak(), P("6. IPI (linha 6.3) — Rotina 1057", "h1")]
    dg = dados["ipi_diag"] or {}
    if dg.get("status") == "ok":
        s.append(P("O IPI de cada item de entrada vem da Rotina 1057 e é casado com o item do Relatório 1096 pela "
                   "filial, código do produto, CFOP e valor (Vl. Total da 1057 = Valor Contábil do 1096). O que não "
                   "casa exato é rateado entre os itens do mesmo produto e CFOP, pelo Valor Contábil."))
        rows_ = [["IPI total da Rotina 1057 (entrada)", _br(dg.get("ipi_total_1057"))],
                 ["Casado item a item (exato)", _br(dg.get("ipi_casado_exato"))],
                 ["Rateado no produto + CFOP", _br(dg.get("ipi_rateado"))],
                 ["Sem item correspondente no 1096", _br(dg.get("ipi_sem_par_no_1096"))],
                 {"valores": ["Levado à linha 6.3", _br(sum((Decimal(str(dg.get(k) or "0"))
                                                             for k in ("ipi_da_6_4", "ipi_da_6_5", "ipi_da_6_7")),
                                                            ZERO))], "b": 1},
                 ["· vindo de dentro da 6.4 (itens com crédito: \"não tributado\" = ICMS + IPI)", _br(dg.get("ipi_da_6_4"))],
                 ["· vindo de dentro da 6.5 (itens de CST sem crédito)", _br(dg.get("ipi_da_6_5"))],
                 ["· vindo de dentro da 6.7 (grupo 5.8)", _br(dg.get("ipi_da_6_7"))],
                 ["Fora da 6.3: IPI que não está no \"não tributado\" do 1096 (não saiu da base)",
                  _br(dg.get("ipi_fora_da_base"))]]
        s.append(grade(["Item", "Valor"], rows_, [largura - 5 * cm, 5 * cm], numericas=(1,),
                       negrito=lambda r: isinstance(r, dict) and r.get("b")))
        s.append(anexo("IPI Rotina 1057"))
    else:
        s.append(P("Não havia Rotina 1057 de entrada nesta competência: o IPI ficou dentro das linhas 6.4/6.5/6.7, "
                   "sem separação na 6.3 (o total e o DARF não mudam)."))

    # ---- 7. LC 224
    s.append(P("7. Linha 4 — Produtos isentos com incidência residual (LC 224/2025)", "h1"))
    if dados["lc224"]:
        rows_ = [[x["ncm"], _br(x["base"]), _br((x["aliq_pis"] or 0) * 100, 4) + "%" if x["aliq_pis"] is not None else "—",
                  _br((x["aliq_cofins"] or 0) * 100, 4) + "%" if x["aliq_cofins"] is not None else "—",
                  _br(x["pis"]), _br(x["cofins"])] for x in dados["lc224"]]
        rows_.append({"valores": ["Total", _br(sum((x["base"] for x in dados["lc224"]), ZERO)), "", "",
                                  _br(sum((x["pis"] or ZERO for x in dados["lc224"]), ZERO)),
                                  _br(sum((x["cofins"] or ZERO for x in dados["lc224"]), ZERO))], "b": 1})
        s.append(grade(["NCM", "Base (não tributado)", "Alíq. PIS", "Alíq. COFINS", "PIS", "COFINS"], rows_,
                       [3 * cm, 4 * cm, 3 * cm, 3 * cm, 3.5 * cm, 3.5 * cm], numericas=(1, 2, 3, 4, 5),
                       negrito=lambda r: isinstance(r, dict) and r.get("b")))
        s.append(anexo("LC 224"))
    else:
        s.append(P("Sem base nesta competência."))

    # ---- 8. lançamentos e receitas
    s.append(P("8. Lançamentos manuais, Receitas Financeiras e saldo anterior", "h1"))
    if dados["lancamentos"]:
        rows_ = [[x["linha"], x["tipo"], x["descricao"], _br(x["base"]), _br(x["pis"]), _br(x["cofins"]), x["situacao"]]
                 for x in dados["lancamentos"]]
        s.append(grade(["Linha", "Tipo", "Descrição", "Base", "PIS", "COFINS", "Situação"], rows_,
                       [1.3 * cm, 6.5 * cm, largura - 23.3 * cm, 3 * cm, 2.5 * cm, 2.5 * cm, 7.5 * cm],
                       numericas=(3, 4, 5)))
    else:
        s.append(P("Nenhum lançamento manual."))
    rows_ = [[r["subitem"], _br(r["valor"])] for r in dados["receitas_financeiras"]]
    s += [Spacer(1, 4), KeepTogether([
        grade(["Receitas Financeiras (linha 3)", "Valor"], rows_, [9 * cm, 4 * cm], numericas=(1,)), Spacer(1, 4),
        P(f"Saldo credor do período anterior: PIS {_br(d['saldo_anterior_pis'])}; COFINS "
          f"{_br(d['saldo_anterior_cofins'])}."), anexo("Lançamentos")])]

    # ---- 9. conferências
    s += [PageBreak(), P("9. Conferências de consistência", "h1"),
          P("Cada tabela de apoio deste relatório foi refeita com as mesmas regras do cálculo e comparada com as "
            "linhas gravadas da apuração.", "pi")]
    rows_ = [[c["descricao"], _br(c["esperado"]), _br(c["obtido"]), _br(c["diferenca"]),
              c["resultado"], c.get("explicacao") or ""] for c in dados["conferencias"]]
    s += [grade(["Checagem", "Esperado", "Obtido", "Diferença", "Resultado", "Explicação"], rows_,
                [9.5 * cm, 3 * cm, 3 * cm, 2.4 * cm, 1.9 * cm, largura - 19.8 * cm], numericas=(1, 2, 3)),
          anexo("Conferências")]

    # ---- 10. pendências
    s.append(P("10. Inconsistências de cadastro pendentes", "h1"))
    inc = dados["inconsistencias"]
    if inc:
        s.append(P(f"{len(inc)} inconsistência(s) pendente(s) no encerramento (não impedem o cálculo)."))
        rows_ = [[x.get("tipo"), x.get("tipo_operacao"), x.get("filial_winthor") or "", x.get("cfop") or "",
                  x.get("cst") if x.get("cst") is not None else "", x.get("descricao")] for x in inc[:40]]
        s.append(grade(["Tipo", "Direção", "Filial", "CFOP", "CST", "Descrição"], rows_,
                       [3.5 * cm, 1.8 * cm, 1.3 * cm, 1.3 * cm, 1.1 * cm, largura - 9 * cm]))
        if len(inc) > 40:
            s.append(P(f"... e mais {len(inc) - 40}.", "pi"))
        s.append(anexo("Inconsistências"))
    else:
        s.append(P("Nenhuma."))

    # ---- 11. anexo
    s.append(P(f"11. Anexo — {nome_anexo}", "h1"))
    s.append(P("A planilha anexa faz parte deste relatório e traz, em abas, todas as tabelas e os itens usados no "
               "cálculo:"))
    s.append(grade(["Aba", "Conteúdo"], [[a, b] for a, b in dados["abas_anexo"]], [5 * cm, largura - 5 * cm]))

    doc.build(s, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
