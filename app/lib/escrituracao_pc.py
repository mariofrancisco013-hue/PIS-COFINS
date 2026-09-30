"""
Relatório da escrituração PIS/COFINS — Lucro Real (29/09/2026, migração 017).

Pedido do usuário: "o relatório deve conter tudo que foi utilizado para chegar nos valores do DARF de PIS e
COFINS, explicações, tabelas de consolidação de itens" — em PDF (memória de cálculo explicada) + Excel, e "o
Excel deve ser informado como anexo" (o PDF cita a planilha como Anexo e aponta a aba de cada detalhe).

Este módulo só MONTA os dados (`montar_escrituracao`). A geração dos arquivos está em
`escrituracao_arquivos_pc.py` e o encerramento (que grava os arquivos) em `encerramento_pc.py`.

Princípio: os valores da apuração e do DARF vêm SEMPRE das linhas gravadas (`apuracao_pc_linhas`, recém-
recalculadas no encerramento). As tabelas de apoio (consolidação por CFOP, itens, IPI) são refeitas aqui com
as MESMAS funções do motor de cálculo (`calculo_pis_cofins_lucro_real`) e conferidas contra as linhas
gravadas — cada conferência sai na seção "Conferências" do relatório, com a diferença, se houver.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from lib import calculo_pis_cofins_lucro_real as calc
from lib import lancamentos_manuais_pc as lmpc
from lib.importacao_pc import listar_filiais_grupo
from lib.receitas_financeiras_pc import TIPOS_RECEITA_FINANCEIRA

ZERO = Decimal("0")
CENT = Decimal("0.01")
TOL = Decimal("0.05")


def _d(v):
    if v is None or v == "":
        return ZERO
    return Decimal(str(v))


def _q(v):
    return _d(v).quantize(CENT)


def _detalhe(v):
    if isinstance(v, dict):
        return v
    if not v:
        return {}
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return {}


def _br(v):
    s = f"{_d(v):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {s}"


def _rotulo_filial(f):
    filial = f.get("filial_winthor") or "—"
    return f"Filial {filial} — {f.get('razao_social', '')}"


# ---------------------------------------------------------------------------------------------- textos
METODOLOGIA = [
    ("Regime e alíquotas",
     "Apuração do PIS e da COFINS no regime não cumulativo (Leis 10.637/2002 e 10.833/2003), consolidada por "
     "grupo econômico (CNPJ raiz: matriz e filiais somadas). Alíquotas: PIS 1,65% e COFINS 7,60% sobre a base "
     "líquida; Receitas Financeiras 0,65% e 4% (Decreto 8.426/2015); Produtos da LC 224/2025 com a alíquota "
     "cadastrada por NCM."),
    ("Fontes de dados",
     "Rotina 1024 (Livro RAICMS, modelo P9) — Valor Contábil por CFOP e filial, fonte da base bruta de cada "
     "grupo. Relatório 1096 (combinação de CFOP, CST, NCM e alíquota, item a item) — separa o que sai da base: "
     "ICMS destacado, itens de CST sem débito/crédito e produtos da LC 224/2025. Rotina 1057 (Relatório para "
     "Auditoria) — IPI de cada item de entrada. Lançamentos manuais (aluguéis, depreciação, fretes, serviços, "
     "ICMS Substituição, Exportação), Receitas Financeiras e saldo credor anterior, informados na aplicação."),
    ("Base de cálculo",
     "Para cada grupo de CFOP: Base líquida = Valor Contábil (Rotina 1024) − exclusões do Relatório 1096 "
     "daquele CFOP. PIS e COFINS de cada grupo = base líquida × alíquota. Os grupos \"1.4 Outras Saídas\" e "
     "\"5.8 Outras Entradas\" saem inteiros da base (não geram débito nem crédito). CFOPs de serviço tributado "
     "pelo ISSQN marcados para isso usam o Valor Contábil do Relatório 1096; CFOPs de \"1.4\"/\"5.8\" que não "
     "vieram na Rotina 1024 usam o Valor Contábil do 1096 (preenchimento)."),
    ("Exclusões do débito (linha 2)",
     "2.3 ICMS destacado: coluna \"valor não tributado\" do 1096 dos itens tributados (CST diferente de 6/7), "
     "grupos 1.1/1.2/1.6. 2.4 ICMS Substituição e 2.6 Exportação: lançamentos manuais, descontados do débito "
     "depois que a linha 1 fecha. 2.5 Outras Saídas: Valor Contábil bruto do grupo 1.4. 2.7 CST 6/7: Valor "
     "Contábil dos itens sem débito, grupos 1.1/1.2/1.6. A linha 2 é a soma dos cinco itens."),
    ("Exclusões do crédito (linha 6)",
     "6.3 IPI: IPI da Rotina 1057, casado item a item com o 1096 (filial + produto + CFOP + valor). No 1096 a "
     "coluna \"valor não tributado\" dos itens com crédito é ICMS + IPI, e os itens sem crédito saem inteiros "
     "— o IPI já saía da base dentro das outras linhas; aqui ele é separado e mostrado só na 6.3. 6.4 ICMS "
     "destacado (sem o IPI). 6.5 itens de CST 70/71/73/74/98 (sem direito a crédito), sem o IPI. 6.6 "
     "Exportação: lançamento manual, descontado do crédito depois que a linha 5 fecha. 6.7 Outras Entradas: "
     "Valor Contábil bruto do grupo 5.8, sem o IPI. A linha 6 é a soma dos cinco itens."),
    ("Regras pontuais",
     "Exceções de \"ICMS zero\": CFOP+CST em que a coluna \"não tributado\" do 1096 não é ICMS real (o livro "
     "RAICMS mostra ICMS zero) — o valor não é tratado como ICMS. CFOPs tratados item a item (hoje o 6202 na "
     "saída): o item isento sai como exclusão e o tributado como ICMS. Produtos da LC 224/2025 (linha 4): "
     "valor não tributado dos itens cujo NCM está cadastrado, nos CFOPs de venda e devolução (grupos 1.1 e "
     "1.2)."),
    ("Resultado",
     "Débito total = linha 1 − 2.4 − 2.6 + 3 + 4. Crédito total = linha 5 − 6.6. Saldo = débito − crédito − "
     "saldo credor anterior. DARF = saldo, quando positivo (linhas 11.1/11.2)."),
]

ABAS_ANEXO = [
    ("Leia-me", "Identificação, índice das abas e referência ao relatório em PDF."),
    ("Resumo DARF", "Composição do DARF a partir das linhas da apuração, com fórmulas."),
    ("Apuração", "Todas as linhas da apuração: base, PIS, COFINS e observações."),
    ("Consolidação Débito", "Por grupo e CFOP de saída: Valor Contábil, exclusões (2.3/2.5/2.7), base líquida, "
                            "PIS e COFINS."),
    ("Consolidação Crédito", "Por grupo e CFOP de entrada: Valor Contábil, exclusões (6.3/6.4/6.5/6.7), base "
                             "líquida, PIS e COFINS."),
    ("CFOP x CST", "Itens do Relatório 1096 agrupados por direção, CFOP e CST, com a linha da apuração."),
    ("Itens Saída", "Cada item do Relatório 1096 de saída e em qual linha da apuração ele entrou."),
    ("Itens Entrada", "Cada item do Relatório 1096 de entrada, o IPI casado da Rotina 1057 e a linha."),
    ("IPI Rotina 1057", "Itens da Rotina 1057 com IPI e como cada um foi casado com o 1096."),
    ("LC 224", "Base e PIS/COFINS da linha 4 por NCM."),
    ("Lançamentos", "Lançamentos manuais, Receitas Financeiras e saldo credor anterior."),
    ("Rotina 1024", "Valor Contábil e ICMS por filial e CFOP, como importados do livro RAICMS."),
    ("Conferência 1024x1096", "Comparação por CFOP entre a Rotina 1024 e o Relatório 1096."),
    ("Conferências", "Checagens de consistência do cálculo, com diferença."),
    ("Inconsistências", "Inconsistências de cadastro ainda pendentes na competência."),
    ("Metodologia", "Regras usadas no cálculo."),
]


# ---------------------------------------------------------------------------------------------- montagem
def montar_escrituracao(session, competencia_id, usuario=None, versao=None):
    comp = session.execute(text("""
        select id, cnpj_raiz, ano, mes, status from competencias where id = :cid
    """), {"cid": competencia_id}).mappings().first()
    if comp is None:
        raise ValueError("Competência não encontrada.")

    linhas_raw = session.execute(text("""
        select linha, descricao, valor_pis, valor_cofins, manual, detalhe, calculado_em
        from apuracao_pc_linhas where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()
    if not linhas_raw:
        raise ValueError("A apuração desta competência ainda não foi calculada.")
    linhas_raw = calc.ordenar_linhas_para_exibicao([dict(r) for r in linhas_raw])

    filiais = listar_filiais_grupo(session, comp["cnpj_raiz"])
    rotulo_por_id = {f["id"]: _rotulo_filial(f) for f in filiais}
    nome_grupo = next((f["razao_social"] for f in filiais if "matriz" in (f["razao_social"] or "").lower()),
                      filiais[0]["razao_social"] if filiais else comp["cnpj_raiz"])

    linhas = []
    T = {}
    for r in linhas_raw:
        det = _detalhe(r["detalhe"])
        secao, _ordem, nivel = calc.LAYOUT_LINHAS.get(r["linha"], ("Outras linhas", 999, 1))
        item = {
            "linha": r["linha"], "descricao": r["descricao"], "secao": secao, "nivel": nivel,
            "base": _d(det["base_total"]) if det.get("base_total") not in (None, "") else None,
            "base_liquida": _d(det["base_liquida"]) if det.get("base_liquida") not in (None, "") else None,
            "pis": _q(r["valor_pis"]), "cofins": _q(r["valor_cofins"]),
            "observacao": det.get("observacao"), "nota": det.get("nota"), "detalhe": det,
        }
        linhas.append(item)
        T[r["linha"]] = item
    calculado_em = max((r["calculado_em"] for r in linhas_raw if r["calculado_em"]), default=None)

    def pc(linha):
        l = T.get(linha)
        return (l["pis"], l["cofins"]) if l else (ZERO, ZERO)

    # ---- DARF (composição a partir das linhas gravadas)
    comp_darf = []
    for rotulo, linha, sinal in [
        ("(1) Total das Receitas Tributáveis — débito dos grupos de CFOP", "1", 1),
        ("(2.4) ICMS Substituição — lançamento manual", "2.4", -1),
        ("(2.6) Exportação (débito) — lançamento manual", "2.6", -1),
        ("(3) Receitas Financeiras", "3", 1),
        ("(4) Produtos LC 224/2025", "4", 1),
    ]:
        p, c = pc(linha)
        comp_darf.append({"grupo": "Débito", "descricao": rotulo, "linha": linha, "sinal": sinal, "pis": p, "cofins": c})
    for rotulo, linha, sinal in [
        ("(5) Total de Créditos", "5", 1),
        ("(6.6) Exportação (crédito) — lançamento manual", "6.6", -1),
    ]:
        p, c = pc(linha)
        comp_darf.append({"grupo": "Crédito", "descricao": rotulo, "linha": linha, "sinal": sinal, "pis": p, "cofins": c})
    debito_pis = sum((x["pis"] * x["sinal"] for x in comp_darf if x["grupo"] == "Débito"), ZERO)
    debito_cofins = sum((x["cofins"] * x["sinal"] for x in comp_darf if x["grupo"] == "Débito"), ZERO)
    credito_pis = sum((x["pis"] * x["sinal"] for x in comp_darf if x["grupo"] == "Crédito"), ZERO)
    credito_cofins = sum((x["cofins"] * x["sinal"] for x in comp_darf if x["grupo"] == "Crédito"), ZERO)
    saldo_ant_pis, saldo_ant_cofins = pc("8.1")[0], pc("8.2")[1]
    saldo_pis = debito_pis - credito_pis - saldo_ant_pis
    saldo_cofins = debito_cofins - credito_cofins - saldo_ant_cofins
    darf_pis, darf_cofins = pc("11.1")[0], pc("11.2")[1]
    darf = {
        "debito_pis": debito_pis, "debito_cofins": debito_cofins,
        "credito_pis": credito_pis, "credito_cofins": credito_cofins,
        "saldo_anterior_pis": saldo_ant_pis, "saldo_anterior_cofins": saldo_ant_cofins,
        "saldo_pis": saldo_pis, "saldo_cofins": saldo_cofins,
        "darf_pis": darf_pis, "darf_cofins": darf_cofins, "darf_total": darf_pis + darf_cofins,
        "composicao": comp_darf,
    }

    # ---- dados de apoio, com as mesmas funções do motor
    resumo_1024 = [dict(r) for r in session.execute(text("""
        select r.empresa_id, r.tipo_operacao, r.cfop, cpe.grupo, cpe.descricao, r.valor_contabil, r.valor_icms
        from resumo_1024_pc r join cfop_pis_cofins_efetivo cpe on cpe.codigo = r.cfop
        where r.competencia_id = :cid
        order by r.tipo_operacao, r.cfop, r.empresa_id
    """), {"cid": competencia_id}).mappings().all()]
    cfop_info = {r["codigo"]: dict(r) for r in session.execute(text(
        "select codigo, descricao, grupo, usa_base_1096 from cfop_pis_cofins_efetivo")).mappings().all()}

    exc_cst = {
        "entrada": calc._somar_exclusao_cst_por_cfop(session, competencia_id, "entrada", calc.CSTS_EXCLUSAO_ENTRADA,
                                                     cfops_item_a_item=calc.CFOPS_ITEM_A_ITEM_ENTRADA),
        "saida": calc._somar_exclusao_cst_por_cfop(session, competencia_id, "saida", calc.CSTS_EXCLUSAO_SAIDA,
                                                   cfops_item_a_item=calc.CFOPS_ITEM_A_ITEM_SAIDA),
    }
    icms_correto = {
        "entrada": calc._somar_icms_nao_excluido_por_cfop(session, competencia_id, "entrada",
                                                          calc.CSTS_EXCLUSAO_ENTRADA,
                                                          cfops_item_a_item=calc.CFOPS_ITEM_A_ITEM_ENTRADA),
        "saida": calc._somar_icms_nao_excluido_por_cfop(session, competencia_id, "saida", calc.CSTS_EXCLUSAO_SAIDA,
                                                        cfops_item_a_item=calc.CFOPS_ITEM_A_ITEM_SAIDA),
    }
    override = {t: calc._carregar_override_1096_por_cfop(session, competencia_id, t) for t in ("entrada", "saida")}
    cfops_1024 = {t: {r["cfop"] for r in resumo_1024 if r["tipo_operacao"] == t} for t in ("entrada", "saida")}
    fallback = {
        "saida": calc._carregar_fallback_1096_cfops_ausentes_1024(session, competencia_id, "saida", "1.4",
                                                                  cfops_1024["saida"]),
        "entrada": calc._carregar_fallback_1096_cfops_ausentes_1024(session, competencia_id, "entrada", "5.8",
                                                                    cfops_1024["entrada"]),
    }
    casamento = calc._casar_ipi_1057_entrada(session, competencia_id)
    ipi_item = casamento["ipi_item"]
    excecoes_icms_zero = {(r["tipo_operacao"], r["cfop"], r["cst"]) for r in session.execute(text(
        "select tipo_operacao, cfop, cst from icms_zero_excecao_pc where ativo")).mappings().all()}

    # ---- consolidação por grupo e CFOP (mesma conta de `_base_por_grupo`)
    consolidacao = {"saida": [], "entrada": []}
    for tipo, grupos, catchall in (("saida", calc.GRUPOS_DEBITO, "1.4"), ("entrada", calc.GRUPOS_CREDITO, "5.8")):
        for grupo in grupos:
            contabil, fonte = {}, {}
            for r in resumo_1024:
                if r["tipo_operacao"] == tipo and r["grupo"] == grupo:
                    contabil[r["cfop"]] = contabil.get(r["cfop"], ZERO) + _d(r["valor_contabil"])
                    fonte[r["cfop"]] = "Rotina 1024"
            if grupo == catchall:
                for cfop, v in fallback[tipo].items():
                    if cfop not in contabil:
                        contabil[cfop] = _d(v)
                        fonte[cfop] = "1096 (CFOP ausente da 1024)"
            for cfop, (g, v) in override[tipo].items():
                if g == grupo:
                    contabil[cfop] = _d(v)
                    fonte[cfop] = "1096 (serviço/ISSQN)"
            for cfop in sorted(contabil):
                bruto = contabil[cfop]
                icms = _d(icms_correto[tipo].get(cfop))
                cst = _d(exc_cst[tipo].get(cfop))
                linha = {"grupo": grupo, "grupo_desc": grupos[grupo], "cfop": cfop,
                         "descricao": (cfop_info.get(cfop) or {}).get("descricao"), "fonte": fonte[cfop],
                         "contabil": bruto, "ipi": ZERO, "icms": ZERO, "cst": ZERO, "outras": ZERO, "liquido": ZERO}
                if grupo == catchall:
                    ipi = ZERO
                    if tipo == "entrada":
                        ipi = sum((ipi_item.get(i["id"], ZERO) for i in casamento["rows_1096"] if i["cfop"] == cfop), ZERO)
                    linha["ipi"] = ipi
                    linha["outras"] = bruto - ipi
                else:
                    linha["liquido"] = bruto - icms - cst
                    if tipo == "entrada":
                        ipi_lim = ipi_exc = ZERO
                        for i in casamento["rows_1096"]:
                            if i["cfop"] != cfop or i["id"] not in ipi_item:
                                continue
                            v = ipi_item[i["id"]]
                            if i["cst"] in calc.CSTS_EXCLUSAO_ENTRADA:
                                ipi_exc += v
                            else:
                                ipi_lim += min(v, max(_d(i["valor_nao_tributado"]), ZERO))
                        linha["ipi"] = ipi_lim + ipi_exc
                        linha["icms"] = icms - ipi_lim
                        linha["cst"] = cst - ipi_exc
                    else:
                        linha["icms"] = icms
                        linha["cst"] = cst
                linha["pis"], linha["cofins"] = calc._pis_cofins_da_base(linha["liquido"])
                consolidacao[tipo].append(linha)

    # ---- itens do 1096 com a linha da apuração
    ncms_lc224 = calc._carregar_ncms_lc224(session)
    cfops_lc224 = {r["cfop"] for r in resumo_1024 if r["tipo_operacao"] == "saida" and r["grupo"] in ("1.1", "1.2")}
    cfops_catchall = {
        "saida": {c for c, i in cfop_info.items() if i["grupo"] == "1.4" and (c in cfops_1024["saida"] or c in fallback["saida"])},
        "entrada": {c for c, i in cfop_info.items() if i["grupo"] == "5.8" and (c in cfops_1024["entrada"] or c in fallback["entrada"]
                                                                                  or c in override["entrada"])},
    }
    itens_raw = session.execute(text("""
        select id, empresa_id, tipo_operacao, produto_codigo, ncm, cst, cfop, valor_contabil, valor_tributado,
               valor_nao_tributado
        from relatorio_pc_itens where competencia_id = :cid order by tipo_operacao, cfop, id
    """), {"cid": competencia_id}).mappings().all()
    itens = {"saida": [], "entrada": []}
    for r in itens_raw:
        tipo = r["tipo_operacao"]
        contabil, trib, nao_trib = _d(r["valor_contabil"]), _d(r["valor_tributado"]), _d(r["valor_nao_tributado"])
        grupo = (cfop_info.get(r["cfop"]) or {}).get("grupo")
        it = {"filial": rotulo_por_id.get(r["empresa_id"], str(r["empresa_id"])), "produto": r["produto_codigo"],
              "ncm": r["ncm"], "cst": r["cst"], "cfop": r["cfop"], "grupo": grupo, "contabil": contabil,
              "tributado": trib, "nao_tributado": nao_trib, "ipi": ZERO, "linha": "", "valor_linha": ZERO,
              "ipi_6_3": ZERO, "base_liquida": ZERO, "obs": ""}
        obs = []
        if abs(contabil - trib - nao_trib) > TOL:
            obs.append("Valor Contábil ≠ Tributado + Não Tributado no 1096 (dado do Winthor)")
        if tipo == "saida":
            excluidos = calc.CSTS_EXCLUSAO_SAIDA
            if grupo is None:
                it["linha"] = "Fora — CFOP sem grupo"
            elif r["cfop"] in cfops_catchall["saida"]:
                it["linha"], it["valor_linha"] = "2.5", contabil
            elif grupo not in calc.GRUPOS_DEBITO:
                it["linha"] = f"Fora — grupo {grupo}"
            elif r["cfop"] not in cfops_1024["saida"]:
                it["linha"] = "Fora — CFOP sem Rotina 1024"
            elif r["cfop"] in calc.CFOPS_ITEM_A_ITEM_SAIDA:
                if trib == 0:
                    it["linha"], it["valor_linha"] = "2.7", contabil
                    obs.append(f"CFOP {r['cfop']} tratado item a item: item isento")
                else:
                    it["linha"], it["valor_linha"] = "2.3", nao_trib
                    it["base_liquida"] = contabil - nao_trib
                    obs.append(f"CFOP {r['cfop']} tratado item a item: item tributado")
            elif r["cst"] in excluidos:
                it["linha"], it["valor_linha"] = "2.7", contabil
            elif ("saida", r["cfop"], r["cst"]) in excecoes_icms_zero:
                it["linha"], it["base_liquida"] = "Base", contabil
                obs.append("Exceção de ICMS zero: \"não tributado\" não é ICMS real")
            else:
                it["linha"], it["valor_linha"] = "2.3", nao_trib
                it["base_liquida"] = contabil - nao_trib
            if r["ncm"] and r["cfop"] in cfops_lc224 and any(v in ncms_lc224 for v in calc._variantes_ncm(str(r["ncm"]))):
                obs.append(f"Linha 4 (LC 224): {_br(nao_trib)} de não tributado")
        else:
            excluidos = calc.CSTS_EXCLUSAO_ENTRADA
            ipi = ipi_item.get(r["id"], ZERO)
            it["ipi"] = ipi
            if grupo is None:
                it["linha"] = "Fora — CFOP sem grupo"
            elif r["cfop"] in cfops_catchall["entrada"]:
                it["linha"], it["valor_linha"], it["ipi_6_3"] = "6.7", contabil - ipi, ipi
            elif grupo not in calc.GRUPOS_CREDITO:
                it["linha"] = f"Fora — grupo {grupo}"
            elif r["cfop"] not in cfops_1024["entrada"]:
                it["linha"] = "Fora — CFOP sem Rotina 1024"
            elif r["cst"] in excluidos:
                it["linha"], it["valor_linha"], it["ipi_6_3"] = "6.5", contabil - ipi, ipi
            elif ("entrada", r["cfop"], r["cst"]) in excecoes_icms_zero:
                it["linha"], it["base_liquida"] = "Base", contabil
                obs.append("Exceção de ICMS zero: \"não tributado\" não é ICMS real")
            else:
                dentro = min(ipi, max(nao_trib, ZERO))
                it["linha"], it["valor_linha"], it["ipi_6_3"] = "6.4", nao_trib - dentro, dentro
                it["base_liquida"] = contabil - nao_trib
                if ipi > dentro + TOL:
                    obs.append(f"IPI {_br(ipi - dentro)} fora do \"não tributado\" — não saiu da base")
            if it["ipi_6_3"]:
                it["linha"] = it["linha"] + " + 6.3"
        it["obs"] = "; ".join(obs)
        itens[tipo].append(it)

    # ---- CFOP x CST
    cfop_cst = {}
    for tipo in ("saida", "entrada"):
        for it in itens[tipo]:
            k = (tipo, it["grupo"], it["cfop"], it["cst"], it["linha"])
            a = cfop_cst.setdefault(k, {"tipo": "Saída" if tipo == "saida" else "Entrada", "grupo": it["grupo"],
                                        "cfop": it["cfop"], "cst": it["cst"], "linha": it["linha"], "n": 0,
                                        "contabil": ZERO, "tributado": ZERO, "nao_tributado": ZERO, "ipi": ZERO,
                                        "valor_linha": ZERO, "ipi_6_3": ZERO})
            a["n"] += 1
            for c in ("contabil", "tributado", "nao_tributado", "ipi", "valor_linha", "ipi_6_3"):
                a[c] += it[c]
    cfop_cst = sorted(cfop_cst.values(), key=lambda a: (a["tipo"] != "Saída", str(a["grupo"]), a["cfop"], a["cst"]))

    # ---- IPI da Rotina 1057
    ipi_1057 = []
    id_para_item = {r["id"]: r for r in casamento["rows_1096"]}
    if casamento["diag"].get("status") == "ok":
        rows57 = session.execute(text("""
            select id, empresa_id, nota, serie, parceiro, produto_codigo, produto_descricao, ncm, cfop, vl_total, vl_ipi
            from relatorio_1057_pc where competencia_id = :cid and tipo_operacao = 'entrada' and vl_ipi <> 0
            order by empresa_id, nota, id
        """), {"cid": competencia_id}).mappings().all()
        for r in rows57:
            tipo_par, id96 = casamento["pares_1057"].get(r["id"], ("sem_par", None))
            item96 = id_para_item.get(id96) if id96 else None
            ipi_1057.append({
                "filial": rotulo_por_id.get(r["empresa_id"], str(r["empresa_id"])), "nota": r["nota"],
                "serie": r["serie"], "fornecedor": r["parceiro"], "produto": r["produto_codigo"],
                "descricao": r["produto_descricao"], "ncm": r["ncm"], "cfop": r["cfop"], "vl_total": _d(r["vl_total"]),
                "vl_ipi": _d(r["vl_ipi"]),
                "casamento": {"exato": "Exato (produto + CFOP + valor)", "rateio": "Rateado no produto + CFOP",
                              "sem_par": "Sem item no 1096"}[tipo_par],
                "cst_1096": item96["cst"] if item96 else None,
            })

    # ---- LC 224 por NCM
    lc224_aliq = {r["ncm"]: (r["aliq_pis"], r["aliq_cofins"]) for r in session.execute(text(
        "select ncm, aliq_pis, aliq_cofins from ncms_lc224_pc where regime = 'real' and ativo")).mappings().all()}
    lc224 = []
    for ncm, base in sorted((T.get("4", {}).get("detalhe", {}).get("base_por_ncm") or {}).items()):
        aliq = next((lc224_aliq[v] for v in calc._variantes_ncm(ncm) if v in lc224_aliq), (None, None))
        base = _d(base)
        lc224.append({"ncm": ncm, "base": base, "aliq_pis": _d(aliq[0]) if aliq[0] is not None else None,
                      "aliq_cofins": _d(aliq[1]) if aliq[1] is not None else None,
                      "pis": base * _d(aliq[0]) if aliq[0] is not None else None,
                      "cofins": base * _d(aliq[1]) if aliq[1] is not None else None})

    # ---- lançamentos, receitas financeiras
    linha_por_tipo = {**{k: v[0] for k, v in calc.LANCAMENTO_TIPO_PARA_LINHA.items()},
                      **{k: v[0] for k, v in calc.LANCAMENTO_TIPO_PARA_LINHA_DEBITO.items()},
                      **{k: v[0] for k, v in calc.LANCAMENTO_TIPO_PARA_LINHA_EXCLUSAO_DEBITO.items()},
                      **{k: v[0] for k, v in calc.LANCAMENTO_TIPO_PARA_LINHA_EXCLUSAO_CREDITO.items()}}
    lancamentos = []
    for l in lmpc.listar(session, competencia_id):
        ignorado = l["tipo"] in calc.TIPOS_LANCAMENTO_DESATIVADOS
        lancamentos.append({"linha": linha_por_tipo.get(l["tipo"], "6.3" if ignorado else ""),
                            "tipo": lmpc.TIPOS.get(l["tipo"], l["tipo"]), "descricao": l["descricao"],
                            "base": _d(l["base_valor"]), "pis": _d(l["valor_pis"]), "cofins": _d(l["valor_cofins"]),
                            "situacao": "Ignorado no cálculo (IPI vem da Rotina 1057)" if ignorado else "Considerado"})
    sub_fin = (T.get("3", {}).get("detalhe", {}) or {}).get("subitens") or {}
    receitas_fin = [{"subitem": rot, "valor": _d(sub_fin.get(t))} for t, rot in TIPOS_RECEITA_FINANCEIRA.items()]

    # ---- Rotina 1024 por filial
    rotina_1024 = [{"filial": rotulo_por_id.get(r["empresa_id"], str(r["empresa_id"])),
                    "tipo": "Saída" if r["tipo_operacao"] == "saida" else "Entrada", "cfop": r["cfop"],
                    "descricao": r["descricao"], "grupo": r["grupo"], "contabil": _d(r["valor_contabil"]),
                    "icms": _d(r["valor_icms"])} for r in resumo_1024]

    conferencia = calc.conferencia_1024_x_1096(session, competencia_id)

    inconsistencias = [dict(r) for r in session.execute(text("""
        select i.tipo, i.tipo_operacao, i.cfop, i.cst, i.descricao, e.filial_winthor
        from inconsistencias_pc i left join empresas e on e.id = i.empresa_id
        where i.competencia_id = :cid and i.status = 'pendente'
        order by i.tipo, i.cfop
    """), {"cid": competencia_id}).mappings().all()]

    conferencias = _conferencias(T, consolidacao, itens, darf)

    avisos = []
    ignorados = [l for l in lancamentos if l["situacao"].startswith("Ignorado")]
    if ignorados:
        avisos.append(f"{len(ignorados)} lançamento(s) manual(is) de IPI ignorado(s) no cálculo — o IPI vem da "
                      f"Rotina 1057 e já sai da base (ver aba Lançamentos).")
    diag = (T.get("6.3", {}).get("detalhe") or {}).get("ipi_1057") or {}
    if diag.get("status") == "sem_1057":
        avisos.append("Nenhuma Rotina 1057 de Entrada importada — o IPI ficou dentro das linhas 6.4/6.5/6.7.")
    if diag.get("empresas_com_1096_sem_1057"):
        nomes = ", ".join(rotulo_por_id.get(e, str(e)) for e in diag["empresas_com_1096_sem_1057"])
        avisos.append(f"Filial(is) com Relatório 1096 de Entrada sem Rotina 1057: {nomes}.")
    if _d(diag.get("ipi_fora_da_base")) > 0:
        avisos.append(f"IPI de {_br(diag['ipi_fora_da_base'])} da Rotina 1057 não entrou na 6.3: nesses itens o IPI "
                      f"não está na coluna \"não tributado\" do 1096, ou seja, não saiu da base.")
    n_defeito = sum(1 for t in ("saida", "entrada") for it in itens[t] if "Valor Contábil ≠" in it["obs"])
    if n_defeito:
        avisos.append(f"{n_defeito} item(ns) do 1096 com Valor Contábil diferente de Tributado + Não Tributado "
                      f"(dado do Winthor) — ver coluna Observação nas abas de itens.")
    if inconsistencias:
        avisos.append(f"{len(inconsistencias)} inconsistência(s) de cadastro pendente(s) no encerramento (aba "
                      f"Inconsistências).")

    return {
        "meta": {
            "competencia_id": competencia_id, "cnpj_raiz": comp["cnpj_raiz"], "nome_grupo": nome_grupo,
            "ano": comp["ano"], "mes": comp["mes"], "periodo": f"{int(comp['mes']):02d}/{comp['ano']}",
            "filiais": [{"rotulo": _rotulo_filial(f), "cnpj": f.get("cnpj")} for f in filiais],
            "gerado_em": datetime.now(timezone.utc), "gerado_por": usuario, "versao": versao,
            "calculado_em": calculado_em,
        },
        "linhas": linhas, "darf": darf, "consolidacao": consolidacao, "itens": itens, "cfop_cst": cfop_cst,
        "ipi_1057": ipi_1057, "ipi_diag": diag, "lc224": lc224, "lancamentos": lancamentos,
        "receitas_financeiras": receitas_fin, "rotina_1024": rotina_1024, "conferencia_1024_1096": conferencia,
        "conferencias": conferencias, "inconsistencias": inconsistencias, "avisos": avisos,
        "metodologia": METODOLOGIA, "abas_anexo": ABAS_ANEXO,
    }


def _conferencias(T, consolidacao, itens, darf):
    out = []

    def add(descricao, esperado, obtido, explicacao="", explicada=ZERO):
        dif = _q(obtido) - _q(esperado)
        ok = abs(dif) <= TOL
        resultado = "OK" if ok else "Diferença"
        if not ok and explicada and abs(dif - _q(explicada)) <= TOL:
            ok, resultado = True, "OK (explicada)"
        out.append({"descricao": descricao, "esperado": _q(esperado), "obtido": _q(obtido), "diferenca": dif,
                    "ok": ok, "resultado": resultado, "explicacao": explicacao})

    def base(l):
        return (T.get(l) or {}).get("base") or ZERO

    for tot, filhos in (("2", ["2.3", "2.4", "2.5", "2.6", "2.7"]), ("6", ["6.3", "6.4", "6.5", "6.6", "6.7"])):
        if tot in T:
            add(f"Linha {tot} = soma das linhas {', '.join(filhos)} (base)", sum((base(f) for f in filhos), ZERO), base(tot))
            add(f"Linha {tot} = soma dos filhos (PIS)", sum((T[f]["pis"] for f in filhos if f in T), ZERO), T[tot]["pis"])
            add(f"Linha {tot} = soma dos filhos (COFINS)", sum((T[f]["cofins"] for f in filhos if f in T), ZERO), T[tot]["cofins"])
    if "1" in T:
        add("Linha 1: base bruta − exclusões embutidas (2.3 + 2.5 + 2.7) = base líquida",
            T["1"]["base_liquida"] or ZERO, (T["1"]["base"] or ZERO) - base("2.3") - base("2.5") - base("2.7"))
    if "5" in T:
        add("Linha 5: base bruta − exclusões embutidas (6.3 + 6.4 + 6.5 + 6.7) = base líquida",
            T["5"]["base_liquida"] or ZERO,
            (T["5"]["base"] or ZERO) - base("6.3") - base("6.4") - base("6.5") - base("6.7"))
    for tipo, grupos in (("saida", calc.GRUPOS_DEBITO), ("entrada", calc.GRUPOS_CREDITO)):
        for g in grupos:
            if g not in T:
                continue
            linhas_g = [c for c in consolidacao[tipo] if c["grupo"] == g]
            add(f"Consolidação por CFOP reproduz o grupo {g} (Valor Contábil)", T[g]["base"] or ZERO,
                sum((c["contabil"] for c in linhas_g), ZERO))
            add(f"Consolidação por CFOP reproduz o grupo {g} (base líquida)", T[g]["base_liquida"] or ZERO,
                sum((c["liquido"] for c in linhas_g), ZERO))
    for tipo, mapa in (("saida", {"2.3": "icms", "2.7": "cst", "2.5": "outras"}),
                       ("entrada", {"6.3": "ipi", "6.4": "icms", "6.5": "cst", "6.7": "outras"})):
        for linha, campo in mapa.items():
            if linha in T:
                add(f"Consolidação por CFOP reproduz a linha {linha}", base(linha),
                    sum((c[campo] for c in consolidacao[tipo]), ZERO))
    # itens x linhas
    for tipo, linhas_itens in (("saida", ["2.3", "2.7", "2.5"]), ("entrada", ["6.4", "6.5", "6.7"])):
        for linha in linhas_itens:
            if linha not in T:
                continue
            soma = sum((it["valor_linha"] for it in itens[tipo] if it["linha"].split(" ")[0] == linha), ZERO)
            expl, explicada = "", ZERO
            if linha in ("2.5", "6.7"):
                # a linha usa o Valor Contábil da Rotina 1024 por CFOP; compara CFOP a CFOP com os itens
                por_cfop_itens = {}
                for it in itens[tipo]:
                    if it["linha"].split(" ")[0] == linha:
                        por_cfop_itens[it["cfop"]] = por_cfop_itens.get(it["cfop"], ZERO) + it["valor_linha"]
                difs = []
                for c in consolidacao[tipo]:
                    if c["outras"] or c["cfop"] in por_cfop_itens:
                        d = _q(por_cfop_itens.get(c["cfop"], ZERO) - c["outras"])
                        if d:
                            difs.append((c["cfop"], d))
                explicada = sum((d for _c, d in difs), ZERO)
                if difs:
                    expl = ("A linha usa o Valor Contábil da Rotina 1024 por CFOP. Diferença entre o livro e os itens "
                            "do Relatório 1096: " + "; ".join(f"CFOP {c}: {_br(-d)} na 1024 sem item no 1096"
                                                              if d < 0 else f"CFOP {c}: {_br(d)} a mais nos itens"
                                                              for c, d in difs) + ".")
            add(f"Itens do 1096 somados na linha {linha}", base(linha), soma, expl, explicada)
    if "6.3" in T:
        add("Itens do 1096 somados na linha 6.3 (IPI)", base("6.3"),
            sum((it["ipi_6_3"] for it in itens["entrada"]), ZERO))
    for imposto in ("pis", "cofins"):
        saldo = darf[f"saldo_{imposto}"]
        add(f"DARF {imposto.upper()} = débito − crédito − saldo anterior (quando positivo)",
            darf[f"darf_{imposto}"], saldo if saldo > 0 else ZERO)
    return out
