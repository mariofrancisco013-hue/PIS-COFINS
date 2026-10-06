"""
Composição de cada linha da apuração PIS/COFINS Lucro Real — CFOP × filial (06/10/2026, fix25).

Pedido do usuário: "inclua na aplicação uma forma de conferir o que compõe cada ponto, exemplo esse 5.8".
Decisões (AskUserQuestion): botão 🔍 em cada linha da aba Apuração, detalhe CFOP × filial (sem descer a
item), todas as linhas com valor calculado, e um bloco "Fora da apuração" nas linhas 1 e 5 (CFOP sem
cadastro, sem Rotina 1024 etc.).

Só leitura: refaz, quebrado por filial, exatamente as mesmas regras de `calcular_apuracao_pc`:
  - Rotina 1024 por CFOP; fallback do 1096 para CFOP do catch-all ausente da 1024; override `usa_base_1096`;
  - ICMS = `valor_nao_tributado` dos itens fora dos CSTs excluídos (e fora de `icms_zero_excecao_pc`);
  - CST excluído = Valor Contábil dos itens de CST 6/7 (saída) ou 70/71/73/74/98 (entrada);
  - IPI = casamento Rotina 1057 × 1096 (`_casar_ipi_1057_entrada`), com o mesmo limite por item;
  - escopo das linhas 2.3/2.7/6.4/6.5 = CFOPs presentes na Rotina 1024 dos grupos não catch-all.
Cada composição traz o total e a diferença para o valor gravado na linha (≠ 0 indica que algo foi importado
ou alterado depois do último "Calcular apuração", ou centavos de arredondamento do IPI, que o motor
arredonda por CFOP).
"""
import json
from decimal import Decimal

from sqlalchemy import text

from lib import calculo_pis_cofins_lucro_real as calc
from lib.receitas_financeiras_pc import TIPOS_RECEITA_FINANCEIRA

ZERO = Decimal("0")
TOL = Decimal("0.05")

ORIGEM_1024 = "Rotina 1024"
ORIGEM_FALLBACK = "1096 (CFOP ausente da 1024)"
ORIGEM_OVERRIDE = "1096 (usa base 1096)"

CATCHALL = {"saida": "1.4", "entrada": "5.8"}
GRUPOS = {"saida": calc.GRUPOS_DEBITO, "entrada": calc.GRUPOS_CREDITO}
CSTS_EXCL = {"saida": calc.CSTS_EXCLUSAO_SAIDA, "entrada": calc.CSTS_EXCLUSAO_ENTRADA}
ITEM_A_ITEM = {"saida": calc.CFOPS_ITEM_A_ITEM_SAIDA, "entrada": calc.CFOPS_ITEM_A_ITEM_ENTRADA}

# Linhas que ganham o botão 🔍 na tela (8.x só quando tem valor — ver a página).
LINHAS_COM_COMPOSICAO = (
    set(calc.GRUPOS_DEBITO) | set(calc.GRUPOS_CREDITO)
    | {"1", "2", "5", "6", "2.3", "2.5", "2.7", "6.3", "6.4", "6.5", "6.7", "3", "4"}
    | {"1.3", "1.5", "2.4", "2.6", "5.3", "5.4", "5.6", "5.9", "6.6"}
    | {"8.1", "8.2", "9.1", "9.2", "11.1", "11.2", "11.3"}
)

# Tipos de coluna (para a tela formatar): "txt", "int", "moeda", "aliq"
COL_CFOP = ("cfop", "CFOP", "txt")
COL_DESC = ("descricao", "Descrição", "txt")
COL_FILIAL = ("filial", "Filial", "txt")
COL_ORIGEM = ("origem", "Origem do valor", "txt")


def _d(v):
    if v is None or v == "":
        return ZERO
    return Decimal(str(v))


def _detalhe(v):
    if isinstance(v, dict):
        return v
    if not v:
        return {}
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return {}


def _somar(dic, chave, valor):
    dic[chave] = dic.get(chave, ZERO) + valor


def montar_composicao(session, competencia_id):
    """{linha: composição} para todas as linhas com valor calculado. Composição = {"titulo", "explicacao",
    "colunas": [(chave, rótulo, tipo)], "linhas": [dict], "coluna_total", "total", "valor_gravado",
    "diferenca", "bate", "fora": [dict] | None, "colunas_fora", "aviso"}."""
    gravadas = {r["linha"]: dict(r) for r in session.execute(text("""
        select linha, descricao, valor_pis, valor_cofins, manual, detalhe
        from apuracao_pc_linhas where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()}
    for r in gravadas.values():
        r["detalhe"] = _detalhe(r["detalhe"])
    if not gravadas:
        return {}

    filial = {r["id"]: (r["filial_winthor"] or str(r["id"])) for r in session.execute(text(
        "select id, filial_winthor from empresas")).mappings().all()}
    cfop_info = {r["codigo"]: dict(r) for r in session.execute(text(
        "select codigo, descricao, grupo, usa_base_1096 from cfop_pis_cofins_efetivo")).mappings().all()}

    resumo = [dict(r) for r in session.execute(text("""
        select empresa_id, tipo_operacao, cfop, valor_contabil from resumo_1024_pc where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()]
    itens = [dict(r) for r in session.execute(text("""
        select id, empresa_id, tipo_operacao, cfop, cst, ncm, valor_contabil, valor_tributado, valor_nao_tributado
        from relatorio_pc_itens where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()]
    excecoes = {(r["tipo_operacao"], r["cfop"], r["cst"]) for r in session.execute(text(
        "select tipo_operacao, cfop, cst from icms_zero_excecao_pc where ativo")).mappings().all()}
    ipi_item = calc._casar_ipi_1057_entrada(session, competencia_id)["ipi_item"]

    def grupo_de(cfop):
        info = cfop_info.get(cfop)
        return info["grupo"] if info else None

    def desc_de(cfop):
        info = cfop_info.get(cfop)
        return info["descricao"] if info else "(sem cadastro)"

    def rot(emp):
        return filial.get(emp, str(emp))

    comp = {}
    fora = {}
    aux = {}  # por tipo: estruturas reaproveitadas pelas linhas 2.x/6.x

    for tipo in ("saida", "entrada"):
        grupos = GRUPOS[tipo]
        catchall = CATCHALL[tipo]
        excl = CSTS_EXCL[tipo]
        item_a_item = ITEM_A_ITEM[tipo]
        resumo_t = [r for r in resumo if r["tipo_operacao"] == tipo]
        itens_t = [i for i in itens if i["tipo_operacao"] == tipo]
        # o motor só enxerga linhas da 1024 com CFOP cadastrado (join com cfop_pis_cofins_efetivo)
        cfops_1024 = {r["cfop"] for r in resumo_t if r["cfop"] in cfop_info}

        # ---- valor contábil por (grupo, cfop, filial) + origem — mesma montagem de _base_por_grupo
        contabil = {}   # (cfop, emp) -> valor
        origem = {}     # cfop -> origem
        for r in resumo_t:
            g = grupo_de(r["cfop"])
            if g in grupos:
                _somar(contabil, (r["cfop"], r["empresa_id"]), _d(r["valor_contabil"]))
                origem[r["cfop"]] = ORIGEM_1024
        vc_1096 = {}
        for i in itens_t:
            _somar(vc_1096, (i["cfop"], i["empresa_id"]), _d(i["valor_contabil"]))
        cfops_1096 = {c for c, _e in vc_1096}
        for cfop in cfops_1096:
            g = grupo_de(cfop)
            if g == catchall and cfop not in cfops_1024:
                for (c, e), v in vc_1096.items():
                    if c == cfop:
                        contabil[(c, e)] = v
                origem[cfop] = ORIGEM_FALLBACK
        for cfop in cfops_1096:
            info = cfop_info.get(cfop)
            if info and info["usa_base_1096"] and info["grupo"] in grupos:
                for k in [k for k in contabil if k[0] == cfop]:
                    del contabil[k]
                for (c, e), v in vc_1096.items():
                    if c == cfop:
                        contabil[(c, e)] = v
                origem[cfop] = ORIGEM_OVERRIDE

        # ---- ICMS, CST excluído e IPI por (cfop, filial), mesmos critérios do motor
        icms, cst_exc, n_icms, n_cst, csts_por = {}, {}, {}, {}, {}
        ipi_lim, ipi_bruto, ipi_exc = {}, {}, {}
        for i in itens_t:
            k = (i["cfop"], i["empresa_id"])
            trib, nt, vc = _d(i["valor_tributado"]), _d(i["valor_nao_tributado"]), _d(i["valor_contabil"])
            if i["cfop"] in item_a_item:
                entra_icms, entra_cst = trib > 0, trib == 0
            else:
                entra_icms, entra_cst = i["cst"] not in excl, i["cst"] in excl
            if entra_icms and (tipo, i["cfop"], i["cst"]) not in excecoes:
                _somar(icms, k, nt)
                n_icms[k] = n_icms.get(k, 0) + 1
            if entra_cst:
                _somar(cst_exc, k, vc)
                n_cst[k] = n_cst.get(k, 0) + 1
                csts_por.setdefault(k, set()).add(i["cst"])
            if tipo == "entrada" and ipi_item.get(i["id"]):
                ipi = ipi_item[i["id"]]
                if i["cst"] in excl:
                    _somar(ipi_exc, k, ipi)
                else:
                    _somar(ipi_lim, k, min(ipi, max(nt, ZERO)))
                    _somar(ipi_bruto, k, ipi)

        # escopo das linhas de ICMS/CST: CFOPs da 1024 nos grupos não catch-all (`_somar_exclusao_cst_escopada`)
        escopo = {r["cfop"] for r in resumo_t
                  if r["cfop"] in cfop_info and grupo_de(r["cfop"]) in grupos and grupo_de(r["cfop"]) != catchall}
        cfops_catchall = {c for (c, _e) in contabil if grupo_de(c) == catchall}
        aux[tipo] = dict(contabil=contabil, origem=origem, icms=icms, cst_exc=cst_exc, n_icms=n_icms,
                         n_cst=n_cst, csts_por=csts_por, ipi_lim=ipi_lim, ipi_bruto=ipi_bruto, ipi_exc=ipi_exc,
                         escopo=escopo, cfops_catchall=cfops_catchall)

        # ---- linhas de grupo (1.1 … 1.6 / 5.1 … 5.8)
        for grupo, descricao in grupos.items():
            cfops_g = {c for (c, _e) in contabil if grupo_de(c) == grupo}
            chaves = {k for k in contabil if k[0] in cfops_g}
            if grupo != catchall:
                chaves |= {k for k in list(icms) + list(cst_exc) if k[0] in cfops_g}
            elif tipo == "entrada":
                # IPI de filial que tem o CFOP no 1096 mas não na 1024 também sai do 6.7 (o motor tira por CFOP)
                chaves |= {k for k in list(ipi_bruto) + list(ipi_exc) if k[0] in cfops_g}
            linhas = []
            for (cfop, emp) in sorted(chaves, key=lambda k: (k[0], rot(k[1]))):
                vc = contabil.get((cfop, emp), ZERO)
                l = {"cfop": cfop, "descricao": desc_de(cfop), "filial": rot(emp), "origem": origem.get(cfop, ""),
                     "contabil": vc}
                if grupo == catchall:
                    if tipo == "entrada":
                        ipi = ipi_bruto.get((cfop, emp), ZERO) + ipi_exc.get((cfop, emp), ZERO)
                        l["ipi"] = ipi
                        l["exclusao"] = vc - ipi
                    else:
                        l["exclusao"] = vc
                else:
                    ic, cs = icms.get((cfop, emp), ZERO), cst_exc.get((cfop, emp), ZERO)
                    if tipo == "entrada":
                        il, ie = ipi_lim.get((cfop, emp), ZERO), ipi_exc.get((cfop, emp), ZERO)
                        l["icms"], l["ipi"], l["cst"] = ic - il, il + ie, cs - ie
                    else:
                        l["icms"], l["cst"] = ic, cs
                    l["liquida"] = vc - ic - cs
                linhas.append(l)
            if grupo == catchall:
                lin_exc = "6.7" if tipo == "entrada" else "2.5"
                colunas = [COL_CFOP, COL_DESC, COL_FILIAL, COL_ORIGEM, ("contabil", "Valor contábil", "moeda")]
                if tipo == "entrada":
                    colunas.append(("ipi", "IPI (vai p/ 6.3)", "moeda"))
                colunas.append(("exclusao", f"Vai p/ {lin_exc}", "moeda"))
                expl = (f"Grupo inteiro excluído da base (não gera {'crédito' if tipo == 'entrada' else 'débito'}). "
                        f"Valor contábil da Rotina 1024 por CFOP; CFOP do grupo ausente da 1024 usa o 1096; CFOP "
                        f"marcado \"usa base 1096\" (1933/2933) usa sempre o 1096. "
                        + ("Na exclusão, o IPI desses itens vai para a 6.3 e o restante para a 6.7."
                           if tipo == "entrada" else "O mesmo valor vai inteiro para a 2.5."))
            else:
                colunas = [COL_CFOP, COL_DESC, COL_FILIAL, COL_ORIGEM, ("contabil", "Valor contábil", "moeda"),
                           ("icms", "(-) ICMS", "moeda")]
                if tipo == "entrada":
                    colunas.append(("ipi", "(-) IPI", "moeda"))
                colunas += [("cst", "(-) CST " + "/".join(str(c) for c in excl), "moeda"),
                            ("liquida", "Base líquida", "moeda")]
                expl = ("Valor contábil da Rotina 1024 por CFOP e filial (ou do 1096 nos CFOPs \"usa base 1096\"). "
                        "As colunas de exclusão vêm do Relatório 1096 da mesma filial e mostram para qual linha "
                        "de exclusão cada parte vai: ICMS → "
                        + ("6.4, IPI → 6.3, CST sem crédito → 6.5." if tipo == "entrada" else "2.3, CST 6/7 → 2.7."))
            comp[grupo] = _fechar(f"{grupo} — {descricao}", expl, colunas, linhas, "contabil", gravadas.get(grupo),
                                  "base")

        # ---- fora da apuração (linhas 1 e 5)
        f = []
        for r in resumo_t:
            g = grupo_de(r["cfop"])
            if r["cfop"] not in cfop_info:
                motivo = "CFOP sem cadastro (fica fora de todas as linhas)"
            elif g not in grupos:
                motivo = f"Grupo {g or '—'} não entra na apuração de {'entrada' if tipo == 'entrada' else 'saída'}"
            else:
                continue
            f.append({"cfop": r["cfop"], "descricao": desc_de(r["cfop"]), "filial": rot(r["empresa_id"]),
                      "origem": ORIGEM_1024, "contabil": _d(r["valor_contabil"]), "nao_tributado": None,
                      "motivo": motivo})
        nt_1096 = {}
        for i in itens_t:
            _somar(nt_1096, (i["cfop"], i["empresa_id"]), _d(i["valor_nao_tributado"]))
        for (cfop, emp), vc in sorted(vc_1096.items(), key=lambda kv: (kv[0][0], rot(kv[0][1]))):
            g = grupo_de(cfop)
            if cfop not in cfop_info:
                motivo = "CFOP sem cadastro (fica fora de todas as linhas)"
            elif g not in grupos:
                motivo = f"Grupo {g or '—'} não entra na apuração de {'entrada' if tipo == 'entrada' else 'saída'}"
            elif cfop not in cfops_1024 and g != catchall and origem.get(cfop) != ORIGEM_OVERRIDE:
                motivo = f"CFOP do grupo {g} sem Rotina 1024 — não entra na base nem nas exclusões"
            else:
                continue
            f.append({"cfop": cfop, "descricao": desc_de(cfop), "filial": rot(emp), "origem": "Relatório 1096",
                      "contabil": vc, "nao_tributado": nt_1096.get((cfop, emp), ZERO), "motivo": motivo})
        fora[tipo] = f

    # ---------------------------------------------------------------- exclusões calculadas
    s, e = aux["saida"], aux["entrada"]

    def _linhas_por_chave(dic, escopo, extra=None):
        out = []
        for (cfop, emp), v in sorted(dic.items(), key=lambda kv: (kv[0][0], rot(kv[0][1]))):
            if cfop not in escopo:
                continue
            l = {"cfop": cfop, "descricao": desc_de(cfop), "grupo": grupo_de(cfop), "filial": rot(emp), "valor": v}
            if extra:
                l.update(extra(cfop, emp))
            out.append(l)
        return out

    comp["2.3"] = _fechar(
        "2.3 — ICMS destacado nas saídas",
        "Soma da coluna \"valor não tributado\" do Relatório 1096 dos itens com CST diferente de 6/7 (no CFOP 6202, "
        "dos itens tributados), sem os CFOP+CST cadastrados como \"ICMS zero\". Só CFOPs dos grupos 1.1/1.2/1.6 "
        "presentes na Rotina 1024 (o 1.4 vai inteiro para a 2.5).",
        [COL_CFOP, COL_DESC, ("grupo", "Grupo", "txt"), COL_FILIAL, ("itens", "Itens", "int"),
         ("valor", "ICMS excluído", "moeda")],
        _linhas_por_chave(s["icms"], s["escopo"], lambda c, m: {"itens": s["n_icms"].get((c, m), 0)}),
        "valor", gravadas.get("2.3"), "base")

    comp["2.5"] = _fechar(
        "2.5 — Outras saídas (grupo 1.4)",
        "É o valor contábil bruto do grupo 1.4, CFOP a CFOP — por construção, 2.5 = 1.4.",
        [COL_CFOP, COL_DESC, COL_FILIAL, COL_ORIGEM, ("valor", "Valor", "moeda")],
        [{**l, "valor": l["contabil"]} for l in comp.get("1.4", {}).get("linhas", [])],
        "valor", gravadas.get("2.5"), "base")

    comp["2.7"] = _fechar(
        "2.7 — Saídas com CST 6/7",
        "Valor contábil dos itens do Relatório 1096 com CST 6 ou 7 (no CFOP 6202, dos itens sem valor tributado). "
        "Só CFOPs dos grupos 1.1/1.2/1.6 presentes na Rotina 1024.",
        [COL_CFOP, COL_DESC, ("grupo", "Grupo", "txt"), COL_FILIAL, ("csts", "CSTs", "txt"), ("itens", "Itens", "int"),
         ("valor", "Valor contábil excluído", "moeda")],
        _linhas_por_chave(s["cst_exc"], s["escopo"], lambda c, m: {
            "itens": s["n_cst"].get((c, m), 0),
            "csts": ", ".join(str(x) for x in sorted(s["csts_por"].get((c, m), ())))}),
        "valor", gravadas.get("2.7"), "base")

    # 6.3 — IPI, por CFOP × filial × linha de onde saiu
    linhas_63 = []
    for (cfop, emp) in sorted(set(e["ipi_lim"]) | set(e["ipi_exc"]) | set(e["ipi_bruto"]),
                              key=lambda k: (k[0], rot(k[1]))):
        partes = []
        if cfop in e["cfops_catchall"]:
            partes.append(("6.7", e["ipi_bruto"].get((cfop, emp), ZERO) + e["ipi_exc"].get((cfop, emp), ZERO)))
        elif cfop in e["escopo"]:
            partes.append(("6.4", e["ipi_lim"].get((cfop, emp), ZERO)))
            partes.append(("6.5", e["ipi_exc"].get((cfop, emp), ZERO)))
        for linha_origem, v in partes:
            if v:
                linhas_63.append({"cfop": cfop, "descricao": desc_de(cfop), "grupo": grupo_de(cfop),
                                  "filial": rot(emp), "saiu_de": linha_origem, "valor": v})
    comp["6.3"] = _fechar(
        "6.3 — IPI (Rotina 1057)",
        "IPI da Rotina 1057 de entrada, casado item a item com o Relatório 1096 (filial + produto + CFOP + valor; o "
        "que não casa exato é rateado no mesmo produto + CFOP). Nos itens com crédito, o IPI é limitado ao \"valor "
        "não tributado\" do item. A coluna \"Saiu de\" mostra a linha de onde o IPI foi tirado.",
        [COL_CFOP, COL_DESC, ("grupo", "Grupo", "txt"), COL_FILIAL, ("saiu_de", "Saiu de", "txt"),
         ("valor", "IPI", "moeda")],
        linhas_63, "valor", gravadas.get("6.3"), "base")

    comp["6.4"] = _fechar(
        "6.4 — ICMS destacado nas entradas",
        "Coluna \"valor não tributado\" do Relatório 1096 (= ICMS + IPI) dos itens com CST diferente de "
        "70/71/73/74/98, menos o IPI desses itens, que vai para a 6.3. Só CFOPs dos grupos 5.1/5.2/5.5/5.7 "
        "presentes na Rotina 1024 (o 5.8 vai para a 6.7).",
        [COL_CFOP, COL_DESC, ("grupo", "Grupo", "txt"), COL_FILIAL, ("itens", "Itens", "int"),
         ("nao_trib", "Não tributado 1096", "moeda"), ("ipi", "(-) IPI → 6.3", "moeda"), ("valor", "ICMS (6.4)", "moeda")],
        _linhas_por_chave(e["icms"], e["escopo"], lambda c, m: {
            "itens": e["n_icms"].get((c, m), 0), "nao_trib": e["icms"][(c, m)],
            "ipi": e["ipi_lim"].get((c, m), ZERO), "valor": e["icms"][(c, m)] - e["ipi_lim"].get((c, m), ZERO)}),
        "valor", gravadas.get("6.4"), "base")

    comp["6.5"] = _fechar(
        "6.5 — Entradas com CST 70/71/73/74/98",
        "Valor contábil dos itens do Relatório 1096 com CST sem direito a crédito, menos o IPI desses itens (vai "
        "para a 6.3). Só CFOPs dos grupos 5.1/5.2/5.5/5.7 presentes na Rotina 1024.",
        [COL_CFOP, COL_DESC, ("grupo", "Grupo", "txt"), COL_FILIAL, ("csts", "CSTs", "txt"), ("itens", "Itens", "int"),
         ("bruto", "Valor contábil", "moeda"), ("ipi", "(-) IPI → 6.3", "moeda"), ("valor", "Na 6.5", "moeda")],
        _linhas_por_chave(e["cst_exc"], e["escopo"], lambda c, m: {
            "itens": e["n_cst"].get((c, m), 0),
            "csts": ", ".join(str(x) for x in sorted(e["csts_por"].get((c, m), ()))),
            "bruto": e["cst_exc"][(c, m)], "ipi": e["ipi_exc"].get((c, m), ZERO),
            "valor": e["cst_exc"][(c, m)] - e["ipi_exc"].get((c, m), ZERO)}),
        "valor", gravadas.get("6.5"), "base")

    comp["6.7"] = _fechar(
        "6.7 — Outras entradas (grupo 5.8)",
        "Valor contábil bruto do grupo 5.8, CFOP a CFOP, menos o IPI desses itens (vai para a 6.3) — 5.8 = 6.7 + IPI.",
        [COL_CFOP, COL_DESC, COL_FILIAL, COL_ORIGEM, ("contabil", "Valor contábil (5.8)", "moeda"),
         ("ipi", "(-) IPI → 6.3", "moeda"), ("valor", "Na 6.7", "moeda")],
        [{**l, "valor": l["exclusao"]} for l in comp.get("5.8", {}).get("linhas", [])],
        "valor", gravadas.get("6.7"), "base")

    # ---------------------------------------------------------------- lançamentos manuais
    for linha in ("1.3", "1.5", "2.4", "2.6", "5.3", "5.4", "5.6", "5.9", "6.6"):
        g = gravadas.get(linha)
        if not g:
            continue
        lanc = g["detalhe"].get("lancamentos") or []
        comp[linha] = _fechar(
            f"{linha} — {g['descricao']}", "Lançamentos manuais da aba Ajustes Manuais.",
            [("descricao", "Lançamento", "txt"), ("valor", "Base", "moeda")],
            [{"descricao": x.get("descricao"), "valor": _d(x.get("base"))} for x in lanc],
            "valor", g, "base")

    # ---------------------------------------------------------------- totais 1/2/5/6
    def _filhos(codigo, filhos, titulo, expl, tipo_fora=None):
        g = gravadas.get(codigo)
        if not g:
            return
        linhas = []
        for f_ in filhos:
            gf = gravadas.get(f_)
            if gf is None:
                continue
            linhas.append({"linha": f_, "descricao": gf["descricao"], "valor": _d(gf["detalhe"].get("base_total")),
                           "pis": _d(gf["valor_pis"]), "cofins": _d(gf["valor_cofins"])})
        c = _fechar(titulo, expl, [("linha", "Linha", "txt"), ("descricao", "Descrição", "txt"),
                                    ("valor", "Base", "moeda"), ("pis", "PIS", "moeda"), ("cofins", "COFINS", "moeda")],
                    linhas, "valor", g, "base")
        if tipo_fora:
            c["fora"] = fora[tipo_fora]
            c["colunas_fora"] = [COL_CFOP, COL_DESC, COL_FILIAL, ("origem", "Fonte", "txt"),
                                 ("contabil", "Valor contábil", "moeda"),
                                 ("nao_tributado", "Não tributado (1096)", "moeda"), ("motivo", "Por que ficou fora", "txt")]
        comp[codigo] = c

    _filhos("1", ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6"], "1 — Total das receitas (débito)",
            "Soma do valor bruto das linhas 1.1 a 1.6. O PIS/COFINS de cada linha já sai da base líquida (bruto − "
            "exclusões 2.3/2.5/2.7).", "saida")
    _filhos("2", ["2.3", "2.4", "2.5", "2.6", "2.7"], "2 — Total das exclusões (débito)",
            "Soma literal das linhas 2.3 a 2.7.")
    _filhos("5", ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "5.8", "5.9"], "5 — Total de créditos",
            "Soma do valor bruto das linhas 5.1 a 5.9. O PIS/COFINS de cada linha já sai da base líquida (bruto − "
            "exclusões 6.3/6.4/6.5/6.7).", "entrada")
    _filhos("6", ["6.3", "6.4", "6.5", "6.6", "6.7"], "6 — Total das exclusões (crédito)",
            "Soma literal das linhas 6.3 a 6.7.")
    for codigo, tipo in (("1.4", "saida"), ("5.8", "entrada"), ("2.5", "saida"), ("6.7", "entrada")):
        if codigo in comp and fora[tipo]:
            n = len({x["cfop"] for x in fora[tipo]})
            comp[codigo]["aviso"] = (f"{n} CFOP(s) de {'entrada' if tipo == 'entrada' else 'saída'} ficaram fora da "
                                     f"apuração — veja \"Fora da apuração\" na composição da linha "
                                     f"{'5' if tipo == 'entrada' else '1'}.")

    # ---------------------------------------------------------------- 3 e 4
    g3 = gravadas.get("3")
    if g3:
        sub = g3["detalhe"].get("subitens") or {}
        comp["3"] = _fechar(
            "3 — Receitas financeiras", "Subitens lançados na aba Ajustes Manuais; PIS 0,65% e COFINS 4% sobre a soma.",
            [("descricao", "Subitem", "txt"), ("valor", "Valor", "moeda")],
            [{"descricao": rot_, "valor": _d(sub.get(t))} for t, rot_ in TIPOS_RECEITA_FINANCEIRA.items()],
            "valor", g3, "base")

    g4 = gravadas.get("4")
    if g4:
        lookup = calc._carregar_ncms_lc224(session)
        cfops_lc = {r["cfop"] for r in resumo if r["tipo_operacao"] == "saida" and grupo_de(r["cfop"]) in ("1.1", "1.2")}
        acc = {}
        for i in itens:
            if i["tipo_operacao"] != "saida" or i["ncm"] is None or i["cfop"] not in cfops_lc:
                continue
            par = lookup.get(str(i["ncm"]).strip())
            if not par:
                continue
            k = (str(i["ncm"]).strip(), i["cfop"], i["empresa_id"])
            a = acc.setdefault(k, {"valor": ZERO, "par": par})
            a["valor"] += _d(i["valor_nao_tributado"])
        linhas4 = []
        for (ncm, cfop, emp), a in sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1], rot(kv[0][2]))):
            linhas4.append({"ncm": ncm, "cfop": cfop, "filial": rot(emp), "valor": a["valor"],
                            "aliq_pis": a["par"][0] * 100, "aliq_cofins": a["par"][1] * 100,
                            "pis": a["valor"] * a["par"][0], "cofins": a["valor"] * a["par"][1]})
        comp["4"] = _fechar(
            "4 — Produtos LC 224/2025",
            "Valor não tributado (Relatório 1096, saída) dos itens cujo NCM está cadastrado na tabela da LC 224, só nos "
            "CFOPs de venda e devolução (grupos 1.1/1.2) presentes na Rotina 1024.",
            [("ncm", "NCM", "txt"), COL_CFOP, COL_FILIAL, ("valor", "Não tributado", "moeda"),
             ("aliq_pis", "% PIS", "aliq"), ("aliq_cofins", "% COFINS", "aliq"), ("pis", "PIS", "moeda"),
             ("cofins", "COFINS", "moeda")],
            linhas4, "valor", g4, "base")

    # ---------------------------------------------------------------- 8, 9 e 11 (fórmula)
    def pc(linha):
        g = gravadas.get(linha)
        return (_d(g["valor_pis"]), _d(g["valor_cofins"])) if g else (ZERO, ZERO)

    termos = [("1", "Débito dos grupos de CFOP", 1), ("2.4", "(-) ICMS Substituição", -1),
              ("2.6", "(-) Exportação (débito)", -1), ("3", "Receitas financeiras", 1), ("4", "LC 224/2025", 1),
              ("5", "(-) Créditos", -1), ("6.6", "Exportação (crédito) — devolve ao saldo", 1),
              ("8.1", "(-) Saldo credor anterior", -1)]
    for codigo, idx, nome in (("9.1", 0, "PIS"), ("9.2", 1, "COFINS")):
        if codigo not in gravadas:
            continue
        linhas9 = []
        for lin, rot_, sinal in termos:
            if lin == "8.1" and idx == 1:
                lin = "8.2"
            v = pc(lin)[idx]
            if v:
                linhas9.append({"linha": lin, "descricao": rot_, "valor": v * sinal})
        comp[codigo] = _fechar(f"{codigo} — Saldo final de {nome}",
                               f"Débito − crédito − saldo credor anterior ({nome}).",
                               [("linha", "Linha", "txt"), ("descricao", "Termo", "txt"), ("valor", nome, "moeda")],
                               linhas9, "valor", gravadas[codigo], "pis" if idx == 0 else "cofins")
    for codigo, origem_, idx, nome in (("11.1", "9.1", 0, "PIS"), ("11.2", "9.2", 1, "COFINS")):
        if codigo in gravadas and origem_ in gravadas:
            v = pc(origem_)[idx]
            comp[codigo] = _fechar(f"{codigo} — DARF {nome}",
                                   f"Saldo final da linha {origem_} quando devedor; se credor, o DARF é zero.",
                                   [("linha", "Linha", "txt"), ("descricao", "Termo", "txt"), ("valor", nome, "moeda")],
                                   [{"linha": origem_, "descricao": "Saldo final" + (" (credor → 0)" if v < 0 else ""),
                                     "valor": max(v, ZERO)}],
                                   "valor", gravadas[codigo], "pis" if idx == 0 else "cofins")
    if "11.3" in gravadas:
        comp["11.3"] = _fechar("11.3 — DARF total", "PIS (11.1) + COFINS (11.2).",
                               [("linha", "Linha", "txt"), ("descricao", "Termo", "txt"), ("valor", "Valor", "moeda")],
                               [{"linha": "11.1", "descricao": "DARF PIS", "valor": pc("11.1")[0]},
                                {"linha": "11.2", "descricao": "DARF COFINS", "valor": pc("11.2")[1]}],
                               "valor", gravadas["11.3"], "pis_cofins")
    for codigo, idx, nome in (("8.1", 0, "PIS"), ("8.2", 1, "COFINS")):
        if codigo in gravadas and pc(codigo)[idx]:
            comp[codigo] = _fechar(f"{codigo} — Saldo credor anterior de {nome}", "Informado na aba Ajustes Manuais.",
                                   [("descricao", "Origem", "txt"), ("valor", nome, "moeda")],
                                   [{"descricao": "Saldo credor do período anterior", "valor": pc(codigo)[idx]}],
                                   "valor", gravadas[codigo], "pis" if idx == 0 else "cofins")
    return comp


def _fechar(titulo, explicacao, colunas, linhas, coluna_total, gravada, comparar):
    total = sum((_d(l.get(coluna_total)) for l in linhas), ZERO)
    if gravada is None:
        valor = None
    elif comparar == "base":
        valor = _d(gravada["detalhe"].get("base_total"))
    elif comparar == "pis":
        valor = _d(gravada["valor_pis"])
    elif comparar == "cofins":
        valor = _d(gravada["valor_cofins"])
    else:
        valor = _d(gravada["valor_pis"]) + _d(gravada["valor_cofins"])
    dif = None if valor is None else total - valor
    return {"titulo": titulo, "explicacao": explicacao, "colunas": colunas, "linhas": linhas,
            "coluna_total": coluna_total, "total": total, "valor_gravado": valor, "diferenca": dif,
            "bate": dif is not None and abs(dif) <= TOL, "fora": None, "colunas_fora": None, "aviso": None}
