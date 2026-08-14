"""
Cálculo da apuração PIS/COFINS — Lucro Real, regime não-cumulativo (Leis nº 10.637/2002 e 10.833/2003).

Reproduz a estrutura da planilha em uso pelo usuário (`PIS-COFINS - LUCRO REAL.xls`, aba "PC"), validada por
conferência aritmética contra os valores reais de ABR/MAI/JUN-2026 (ex.: Base Abril = 4.254.191,06; Saldo
Final PIS Abril = 7.889,76 = Débito PIS 70.632,30 − Crédito PIS 62.742,54 — bateu exato). Metodologia
completa (por que soma-se `valor_pis`/`valor_cofins` item a item em vez de recalcular base×alíquota, listas
de CFOP por linha, pontos em aberto) documentada em `claude/metodologia-pis-cofins-lucro-real.md` no projeto
Claude "PIS/COFINS" — leia antes de mexer aqui.

Por que somar valor_pis/valor_cofins direto do item (não base×alíquota de novo): o Relatório 1096 já traz o
PIS/COFINS de cada item calculado pelo Winthor a partir do CST (isenção/monofásico/alíquota zero já zeram a
base do item). Somar os valores já calculados evita reintroduzir as linhas de "Exclusões" (2.x/6.x) que a
planilha original calcula por um caminho mais longo (bruto − exclusões) só para chegar no mesmo número —
aqui chega-se direto, e o resultado bateu exato contra os totais reais da planilha nos testes de abril/maio/
junho (ver metodologia).

ACHADO (14/08/2026, validando contra o arquivo real de julho/2026): a planilha antiga tratava "5.2 (+)
Energia Elétrica" como linha 100% manual (sem CFOP embaixo, ao contrário de 5.1/5.5/5.7/5.8). No Relatório
1096 de julho, porém, o CFOP 1253 (Energia) aparece com PIS/COFINS já calculados pelo Winthor, igual a
qualquer outro CFOP de crédito — então esta versão trata 5.2 como um grupo calculado (CFOP 1253), não mais
manual. Se algum mês vier com energia lançada só na contabilidade (sem passar pelo Winthor com CFOP), essa
parcela ficaria de fora — vale conferir contra o extrato da concessionária de vez em quando.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import text

ALIQ_PIS = Decimal("0.0165")
ALIQ_COFINS = Decimal("0.0760")

GRUPOS_DEBITO = {
    "1.1": "Faturamento Bruto (Mercadorias p/ Revenda)",
    "1.2": "Devolução de Mercadoria de Compra",
    "1.4": "Outras Saídas",
    "1.6": "Demais Operações",
}
GRUPOS_CREDITO = {
    "5.1": "Compra de Mercadorias para Revenda",
    "5.2": "Energia Elétrica",
    "5.5": "Fretes e Armazenagens nas Operações de Venda",
    "5.7": "Devoluções de Vendas",
    "5.8": "Outras Entradas",
}
# Linhas manuais fora do escopo desta versão (ver "Pontos em aberto" na metodologia) — ficam na apuração
# com valor zero e manual=true, para não desaparecer da tela e para o próximo lançamento ser só uma questão
# de estender LANCAMENTOS_TIPO_PARA_LINHA / adicionar a soma correspondente aqui.
LINHAS_PENDENTES_DEBITO = {
    "1.3": "Faturamento Bruto (Prestação de Serviços)",
    "1.5": "Receitas de Aluguel de Bens",
    "3": "Receitas Financeiras (alíquota reduzida 0,65%/4% — Lei 8.426/2015)",
    "2.3": "(-) ICMS Apuração - Destacado Saídas",
    "2.4": "(-) ICMS Substituição",
    "2.6": "(-) Exportação de Mercadorias para o Exterior",
}
LINHAS_PENDENTES_CREDITO = {
    "5.9": "Fretes SUPPLY LOG",
    "6.3": "(-) IPI",
    "6.4": "(-) ICMS Apuração - Destacado Entradas",
    "6.5": "(-) Entradas Isentas da Contribuição (fora do CST)",
    "6.6": "(-) Exportação de Mercadorias para o Exterior",
}

# Lançamentos manuais implementados nesta versão (Aluguéis + Depreciação) — ver lancamentos_manuais_pc.py
LANCAMENTO_TIPO_PARA_LINHA = {
    "aluguel_predio_credito": ("5.3", "Aluguéis pagos a PJ (Prédios)"),
    "aluguel_maquinas_credito": ("5.4", "Aluguéis pagos a PJ (Máquinas e Equipamentos)"),
    "depreciacao_credito": ("5.6", "Depreciações Máquinas e Equip. e Outros Bens do Ativo Imobilizado"),
}


@dataclass
class LinhaApuracaoPC:
    linha: str
    descricao: str
    valor_pis: Decimal
    valor_cofins: Decimal
    manual: bool = False
    detalhe: dict = field(default_factory=dict)


def _dec(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def calcular_apuracao_pc(session, competencia_id: int) -> list[LinhaApuracaoPC]:
    """Calcula as linhas 1.x-11.x da apuração PIS/COFINS Lucro Real. Não grava no banco — quem chama decide
    se persiste (ver salvar_apuracao_pc)."""

    itens = session.execute(text("""
        select ri.tipo_operacao, ri.cfop, cpe.grupo, ri.valor_pis, ri.valor_cofins
        from relatorio_pc_itens ri
        join cfop_pis_cofins_efetivo cpe on cpe.codigo = ri.cfop
        where ri.competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    linhas: list[LinhaApuracaoPC] = []

    # --- débito (saída) ---
    debito_pis_total = Decimal("0")
    debito_cofins_total = Decimal("0")
    for grupo, descricao in GRUPOS_DEBITO.items():
        soma_pis = soma_cofins = Decimal("0")
        det = {}
        for it in itens:
            if it["tipo_operacao"] == "saida" and it["grupo"] == grupo:
                atual = det.get(it["cfop"], {"pis": Decimal("0"), "cofins": Decimal("0")})
                atual["pis"] += _dec(it["valor_pis"])
                atual["cofins"] += _dec(it["valor_cofins"])
                det[it["cfop"]] = atual
        linhas.append(LinhaApuracaoPC(grupo, descricao, soma_pis, soma_cofins,
                                       detalhe={"por_cfop": {k: {kk: str(vv) for kk, vv in v.items()}
                                                              for k, v in det.items()}}))
        debito_pis_total += soma_pis
        debito_cofins_total += soma_cofins

    for linha, descricao in LINHAS_PENDENTES_DEBITO.items():
        linhas.append(LinhaApuracaoPC(linha, descricao, Decimal("0"), Decimal("0"), manual=True))

    linhas.append(LinhaApuracaoPC("1", "Total das Receitas Tributáveis (débito)",
                                   debito_pis_total, debito_cofins_total))

    # --- crédito (entrada) ---
    credito_pis_total = Decimal("0")
    credito_cofins_total = Decimal("0")
    for grupo, descricao in GRUPOS_CREDITO.items():
        det = {}
        soma_pis = soma_cofins = Decimal("0")
        for it in itens:
            if it["tipo_operacao"] == "entrada" and it["grupo"] == grupo:
                soma_pis += _dec(it["valor_pis"])
                soma_cofins += _dec(it["valor_cofins"])
                atual = det.get(it["cfop"], {"pis": Decimal("0"), "cofins": Decimal("0")})
                atual["pis"] += _dec(it["valor_pis"])
                atual["cofins"] += _dec(it["valor_cofins"])
                det[it["cfop"]] = atual
        linhas.append(LinhaApuracaoPC(grupo, descricao, soma_pis, soma_cofins,
                                       detalhe={"por_cfop": {k: {kk: str(vv) for kk, vv in v.items()}
                                                              for k, v in det.items()}}))
        credito_pis_total += soma_pis
        credito_cofins_total += soma_cofins

    # lançamentos manuais (aluguéis, depreciação)
    lancamentos = session.execute(text("""
        select tipo, descricao, base_valor, valor_pis, valor_cofins
        from lancamentos_manuais_pc where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    for tipo, (linha, descricao) in LANCAMENTO_TIPO_PARA_LINHA.items():
        itens_tipo = [l for l in lancamentos if l["tipo"] == tipo]
        soma_pis = sum((_dec(l["valor_pis"]) for l in itens_tipo), Decimal("0"))
        soma_cofins = sum((_dec(l["valor_cofins"]) for l in itens_tipo), Decimal("0"))
        det = {"lancamentos": [{"descricao": l["descricao"], "base": str(l["base_valor"])} for l in itens_tipo]}
        linhas.append(LinhaApuracaoPC(linha, descricao, soma_pis, soma_cofins, detalhe=det))
        credito_pis_total += soma_pis
        credito_cofins_total += soma_cofins

    for linha, descricao in LINHAS_PENDENTES_CREDITO.items():
        linhas.append(LinhaApuracaoPC(linha, descricao, Decimal("0"), Decimal("0"), manual=True))

    linhas.append(LinhaApuracaoPC("5", "Total de Créditos", credito_pis_total, credito_cofins_total))

    # --- saldo credor do período anterior (entrada manual — ver saldo_credor_anterior_pc) ---
    saldo_anterior = session.execute(text("""
        select saldo_pis, saldo_cofins from saldo_credor_anterior_pc where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().first()
    saldo_pis_ant = _dec(saldo_anterior["saldo_pis"]) if saldo_anterior else Decimal("0")
    saldo_cofins_ant = _dec(saldo_anterior["saldo_cofins"]) if saldo_anterior else Decimal("0")
    linhas.append(LinhaApuracaoPC("8.1", "Saldo Credor de PIS do período anterior", saldo_pis_ant,
                                   Decimal("0"), manual=True))
    linhas.append(LinhaApuracaoPC("8.2", "Saldo Credor de COFINS do período anterior", Decimal("0"),
                                   saldo_cofins_ant, manual=True))

    # --- saldo final e DARF ---
    saldo_pis = debito_pis_total - credito_pis_total - saldo_pis_ant
    saldo_cofins = debito_cofins_total - credito_cofins_total - saldo_cofins_ant

    linhas.append(LinhaApuracaoPC("9.1", "Saldo Final Devedor ou (Credor) de PIS - não cumulativo",
                                   saldo_pis, Decimal("0")))
    linhas.append(LinhaApuracaoPC("9.2", "Saldo Final Devedor ou (Credor) de COFINS - não cumulativo",
                                   Decimal("0"), saldo_cofins))

    linhas.append(LinhaApuracaoPC("10.1", "PERD/COMP - Não cumulativa PIS", Decimal("0"), Decimal("0"), manual=True))
    linhas.append(LinhaApuracaoPC("10.2", "PERD/COMP - Não cumulativa COFINS", Decimal("0"), Decimal("0"), manual=True))

    pagar_pis = saldo_pis if saldo_pis > 0 else Decimal("0")
    pagar_cofins = saldo_cofins if saldo_cofins > 0 else Decimal("0")
    linhas.append(LinhaApuracaoPC("11.1", "Líquido a pagar em DARF - TOTAL PIS", pagar_pis, Decimal("0")))
    linhas.append(LinhaApuracaoPC("11.2", "Líquido a pagar em DARF - TOTAL COFINS", Decimal("0"), pagar_cofins))
    linhas.append(LinhaApuracaoPC("11.3", "Líquido a pagar em DARF - TOTAL PIS E COFINS",
                                   pagar_pis, pagar_cofins))

    return linhas


def salvar_apuracao_pc(session, competencia_id: int, linhas: list[LinhaApuracaoPC]):
    import json
    for l in linhas:
        session.execute(text("""
            insert into apuracao_pc_linhas
                (competencia_id, linha, descricao, valor_pis, valor_cofins, manual, detalhe, calculado_em)
            values (:cid, :linha, :descricao, :vpis, :vcofins, :manual, :detalhe, now())
            on conflict (competencia_id, linha) do update
                set descricao = excluded.descricao,
                    valor_pis = excluded.valor_pis,
                    valor_cofins = excluded.valor_cofins,
                    manual = excluded.manual,
                    detalhe = excluded.detalhe,
                    calculado_em = now()
        """), {
            "cid": competencia_id, "linha": l.linha, "descricao": l.descricao,
            "vpis": str(l.valor_pis), "vcofins": str(l.valor_cofins), "manual": l.manual,
            "detalhe": json.dumps(l.detalhe, default=str),
        })
    session.execute(text("update competencias set status = 'calculada' where id = :cid"), {"cid": competencia_id})
    session.commit()
