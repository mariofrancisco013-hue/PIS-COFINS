"""
Exportação dos lançamentos contábeis de PIS/COFINS (Lucro Real) no layout de importação do Winthor —
07/10/2026, fix28 (migração 019).

Pedido do usuário: "preciso ter um botão para que esses lançamentos sejam exportados com base nas
informações da aplicação" (modelo: IMPORTAÇÃO PIS-COFINS.xlsx). Decisões (AskUserQuestion): só Receitas
Financeiras (linha 3), Aluguéis (5.3 + 5.4 somados) e Depreciação (5.6); contas em tabela editável
(`contabilizacao_pc_contas`); filial escolhida no botão, coluna L = código da filial no Winthor (sem o "F").

Layout (sem cabeçalho, uma linha por partida, colunas A–L como na planilha modelo):
  A "C3" · B sequência 1–4 do lançamento · C conta · D data DDMMAAAA (último dia da competência) ·
  E "D"/"C" · F vazio · G valor · H código do histórico (44) · I histórico · J "N" · K vazio · L filial.
Cada evento = 4 linhas: D PIS, D COFINS, C PIS, C COFINS. Evento com PIS e COFINS zerados não é exportado.

Valores: os mesmos do cálculo (PIS/COFINS de cada lançamento manual, já arredondados; Receitas Financeiras
pela alíquota reduzida 0,65%/4% sobre a soma dos subitens). Também compara com as linhas gravadas da
apuração (3, 5.3+5.4, 5.6) e avisa se diferirem (algo mudou depois do último "Calcular apuração").
"""
import calendar
import io
from decimal import Decimal

from sqlalchemy import inspect as sa_inspect, text

from lib.receitas_financeiras_pc import calcular_pis_cofins, carregar_receitas_financeiras

ZERO = Decimal("0")
COL_A = "C3"
COL_J = "N"

EVENTOS = {
    # evento: (rótulo, tipos de lançamento manual | None = receitas financeiras, linhas da apuração)
    "receitas_financeiras": ("Receitas Financeiras (linha 3)", None, ("3",)),
    "aluguel": ("Aluguéis (linhas 5.3 + 5.4)", ("aluguel_predio_credito", "aluguel_maquinas_credito"), ("5.3", "5.4")),
    "depreciacao": ("Depreciação (linha 5.6)", ("depreciacao_credito",), ("5.6",)),
}

COLUNAS_CONTAS = ["evento", "conta_debito_pis", "conta_debito_cofins", "conta_credito_pis", "conta_credito_cofins",
                  "historico_pis", "historico_cofins", "cod_historico", "ativo"]


def tabela_pronta(session) -> bool:
    return sa_inspect(session.get_bind()).has_table("contabilizacao_pc_contas")


def listar_contas(session):
    return [dict(r) for r in session.execute(text(f"""
        select {", ".join(COLUNAS_CONTAS)} from contabilizacao_pc_contas order by ordem, evento
    """)).mappings().all()]


def salvar_contas(session, linhas):
    """`linhas` = lista de dicts com as colunas de COLUNAS_CONTAS (grade editada). Só atualiza eventos existentes.
    Valida todas as linhas antes de gravar qualquer uma (o engine de produção é AUTOCOMMIT)."""
    linhas = [l for l in linhas if l.get("evento") in EVENTOS]
    for l in linhas:
        for c in ("conta_debito_pis", "conta_debito_cofins", "conta_credito_pis", "conta_credito_cofins",
                  "cod_historico"):
            if l.get(c) is None or str(l.get(c)).strip() in ("", "nan", "None"):
                raise ValueError(f"Preencha a coluna {c} do evento {EVENTOS[l['evento']][0]}.")
        for c in ("historico_pis", "historico_cofins"):
            if not str(l.get(c) or "").strip():
                raise ValueError(f"Preencha o histórico ({c}) do evento {EVENTOS[l['evento']][0]}.")
    for l in linhas:
        session.execute(text("""
            update contabilizacao_pc_contas set
                conta_debito_pis = :cdp, conta_debito_cofins = :cdc, conta_credito_pis = :ccp,
                conta_credito_cofins = :ccc, historico_pis = :hp, historico_cofins = :hc, cod_historico = :ch,
                ativo = :at, atualizado_em = now()
            where evento = :ev
        """), {"cdp": int(l["conta_debito_pis"]), "cdc": int(l["conta_debito_cofins"]),
               "ccp": int(l["conta_credito_pis"]), "ccc": int(l["conta_credito_cofins"]),
               "hp": str(l["historico_pis"]).strip(), "hc": str(l["historico_cofins"]).strip(),
               "ch": int(l["cod_historico"]), "at": bool(l.get("ativo", True)), "ev": l["evento"]})
    session.commit()


def codigo_filial(filial_winthor) -> str:
    """Coluna L: código da filial no Winthor sem o prefixo "F" (cadastro tem 'F6' e '59')."""
    s = str(filial_winthor or "").strip()
    if s[:1].upper() == "F":
        s = s[1:]
    return s


def _valores_por_evento(session, competencia_id):
    lanc = session.execute(text("""
        select tipo, valor_pis, valor_cofins from lancamentos_manuais_pc where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()
    out = {}
    for ev, (_rot, tipos, _linhas) in EVENTOS.items():
        if tipos is None:
            base = sum(carregar_receitas_financeiras(session, competencia_id).values(), ZERO)
            out[ev] = calcular_pis_cofins(base)
        else:
            sel = [l for l in lanc if l["tipo"] in tipos]
            out[ev] = (sum((Decimal(str(l["valor_pis"])) for l in sel), ZERO),
                       sum((Decimal(str(l["valor_cofins"])) for l in sel), ZERO))
    return out


def montar_lancamentos(session, competencia_id, filial_winthor):
    """{"linhas": [dict A..L], "resumo": [...], "avisos": [...], "data": 'DDMMAAAA', "filial": str}."""
    comp = session.execute(text("select ano, mes from competencias where id = :cid"),
                           {"cid": competencia_id}).mappings().first()
    if comp is None:
        raise ValueError("Competência não encontrada.")
    ano, mes = int(comp["ano"]), int(comp["mes"])
    data = int(f"{calendar.monthrange(ano, mes)[1]:02d}{mes:02d}{ano}")
    filial = codigo_filial(filial_winthor)
    if not filial:
        raise ValueError("Escolha a filial.")
    col_l = int(filial) if filial.isdigit() else filial

    contas = {c["evento"]: c for c in listar_contas(session)}
    valores = _valores_por_evento(session, competencia_id)
    gravadas = {r["linha"]: (Decimal(str(r["valor_pis"])), Decimal(str(r["valor_cofins"])))
                for r in session.execute(text("""
                    select linha, valor_pis, valor_cofins from apuracao_pc_linhas where competencia_id = :cid
                """), {"cid": competencia_id}).mappings().all()}

    linhas, resumo, avisos = [], [], []
    for ev, (rotulo, _tipos, linhas_apur) in EVENTOS.items():
        c = contas.get(ev)
        pis, cofins = valores[ev]
        if gravadas:
            gp = sum((gravadas.get(l, (ZERO, ZERO))[0] for l in linhas_apur), ZERO)
            gc = sum((gravadas.get(l, (ZERO, ZERO))[1] for l in linhas_apur), ZERO)
            if abs(gp - pis) > Decimal("0.01") or abs(gc - cofins) > Decimal("0.01"):
                avisos.append(f"{rotulo}: valores diferentes da apuração gravada (PIS {gp} × {pis}; COFINS {gc} × "
                              f"{cofins}) — clique em Calcular apuração antes de exportar.")
        if c is None or not c["ativo"]:
            resumo.append({"evento": rotulo, "pis": pis, "cofins": cofins, "situacao": "Desativado nas contas"})
            continue
        if not pis and not cofins:
            resumo.append({"evento": rotulo, "pis": pis, "cofins": cofins, "situacao": "Sem valor — não exportado"})
            continue
        partidas = [
            (1, c["conta_debito_pis"], "D", pis, c["historico_pis"]),
            (2, c["conta_debito_cofins"], "D", cofins, c["historico_cofins"]),
            (3, c["conta_credito_pis"], "C", pis, c["historico_pis"]),
            (4, c["conta_credito_cofins"], "C", cofins, c["historico_cofins"]),
        ]
        for seq, conta, dc, valor, hist in partidas:
            linhas.append({"A": COL_A, "B": seq, "C": int(conta), "D": data, "E": dc, "F": None, "G": valor,
                           "H": int(c["cod_historico"]), "I": hist, "J": COL_J, "K": None, "L": col_l})
        resumo.append({"evento": rotulo, "pis": pis, "cofins": cofins, "situacao": "Exportado"})
    if not gravadas:
        avisos.append("A apuração desta competência ainda não foi calculada.")
    return {"linhas": linhas, "resumo": resumo, "avisos": avisos, "data": f"{data:08d}", "filial": filial,
            "ano": ano, "mes": mes}


def gerar_xlsx(dados) -> bytes:
    """Mesmo layout da planilha modelo: aba Plan1, sem cabeçalho, colunas A–L, valor em formato R$."""
    import xlsxwriter
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("Plan1")
    moeda = wb.add_format({"num_format": '_-"R$"\\ * #,##0.00_-;\\-"R$"\\ * #,##0.00_-;_-"R$"\\ * "-"??_-;_-@_-'})
    for i, l in enumerate(dados["linhas"]):
        for j, col in enumerate("ABCDEFGHIJKL"):
            v = l[col]
            if v is None:
                continue
            if col == "G":
                ws.write_number(i, j, float(v), moeda)
            elif isinstance(v, (int, float)):
                ws.write_number(i, j, v)
            else:
                ws.write_string(i, j, str(v))
    ws.set_column(6, 6, 16)
    ws.set_column(8, 8, 34)
    wb.close()
    return buf.getvalue()


def nome_arquivo(dados, cnpj_raiz):
    return f"Importacao_PIS_COFINS_{cnpj_raiz}_{dados['ano']}-{dados['mes']:02d}_filial{dados['filial']}.xlsx"
