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

LAYOUT (14/08/2026): a tela de apuração usava `order by linha` (ordem alfabética de texto), que embaralha
a sequência de verdade (ex: "10.1" ordena antes de "2"), e mostrava tudo achatado numa tabela só — muito
diferente da planilha original (seções "1- RECEITAS TRIBUTÁVEIS", "2- EXCLUSÕES" etc., sub-itens indentados
embaixo de cada seção). `LAYOUT_LINHAS`/`ORDEM_SECOES`/`ordenar_linhas_para_exibicao()` no fim deste arquivo
resolvem isso — são só de apresentação, não mudam nenhum valor calculado.
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

# Layout de exibição — pedido do usuário em 14/08/2026 ("o layout da apuração está muito diferente da
# planilha"): a tela mostrava as linhas numa ordem alfabética de texto (então "10.1" aparecia antes de
# "2", por exemplo) e tudo achatado numa única tabela, sem as seções/indentação da planilha original. Este
# dicionário é só de APRESENTAÇÃO (não entra no cálculo) — mapeia cada linha para (seção, nível de
# indentação, se é linha de total/destaque). Usado pela página Streamlit para agrupar e ordenar do jeito
# que a planilha `PIS-COFINS - LUCRO REAL.xls` (aba "PC") mostra: Débito → Exclusões do Débito → Receitas
# Financeiras → Crédito → Exclusões do Crédito → Saldo Anterior → Resultado.
SECAO_DEBITO = "1 — Débito (Saída)"
SECAO_EXCLUSOES_DEBITO = "2 — Exclusões do Débito"
SECAO_FINANCEIRAS = "3 — Receitas Financeiras (alíquota reduzida)"
SECAO_CREDITO = "5 — Crédito (Entrada)"
SECAO_EXCLUSOES_CREDITO = "6 — Exclusões do Crédito"
SECAO_SALDO_ANTERIOR = "8 — Saldo do Período Anterior"
SECAO_RESULTADO = "Resultado da Apuração"

ORDEM_SECOES = [
    SECAO_DEBITO, SECAO_EXCLUSOES_DEBITO, SECAO_FINANCEIRAS, SECAO_CREDITO, SECAO_EXCLUSOES_CREDITO,
    SECAO_SALDO_ANTERIOR, SECAO_RESULTADO,
]

# linha -> (seção, ordem dentro da seção, nível [0=total/destaque, 1=sub-item indentado])
LAYOUT_LINHAS = {
    "1.1": (SECAO_DEBITO, 0, 1), "1.2": (SECAO_DEBITO, 1, 1), "1.3": (SECAO_DEBITO, 2, 1),
    "1.4": (SECAO_DEBITO, 3, 1), "1.5": (SECAO_DEBITO, 4, 1), "1.6": (SECAO_DEBITO, 5, 1),
    "1": (SECAO_DEBITO, 6, 0),
    "2.3": (SECAO_EXCLUSOES_DEBITO, 0, 1), "2.4": (SECAO_EXCLUSOES_DEBITO, 1, 1),
    "2.6": (SECAO_EXCLUSOES_DEBITO, 2, 1), "2": (SECAO_EXCLUSOES_DEBITO, 3, 0),
    "3": (SECAO_FINANCEIRAS, 0, 0),
    "5.1": (SECAO_CREDITO, 0, 1), "5.2": (SECAO_CREDITO, 1, 1), "5.3": (SECAO_CREDITO, 2, 1),
    "5.4": (SECAO_CREDITO, 3, 1), "5.5": (SECAO_CREDITO, 4, 1), "5.6": (SECAO_CREDITO, 5, 1),
    "5.7": (SECAO_CREDITO, 6, 1), "5.8": (SECAO_CREDITO, 7, 1), "5.9": (SECAO_CREDITO, 8, 1),
    "5": (SECAO_CREDITO, 9, 0),
    "6.3": (SECAO_EXCLUSOES_CREDITO, 0, 1), "6.4": (SECAO_EXCLUSOES_CREDITO, 1, 1),
    "6.5": (SECAO_EXCLUSOES_CREDITO, 2, 1), "6.6": (SECAO_EXCLUSOES_CREDITO, 3, 1),
    "6": (SECAO_EXCLUSOES_CREDITO, 4, 0),
    "8.1": (SECAO_SALDO_ANTERIOR, 0, 1), "8.2": (SECAO_SALDO_ANTERIOR, 1, 1),
    "9.1": (SECAO_RESULTADO, 0, 0), "9.2": (SECAO_RESULTADO, 1, 0),
    "10.1": (SECAO_RESULTADO, 2, 1), "10.2": (SECAO_RESULTADO, 3, 1),
    "11.1": (SECAO_RESULTADO, 4, 0), "11.2": (SECAO_RESULTADO, 5, 0), "11.3": (SECAO_RESULTADO, 6, 0),
}


def ordenar_linhas_para_exibicao(linhas: list) -> list:
    """Ordena uma lista de linhas (objetos com atributo `.linha`, ou dicts com chave `linha`) na sequência
    de exibição da planilha — usar isso na tela em vez de `order by linha` (ordem de texto), que embaralha
    a sequência (ex: "10.1" viria antes de "2")."""
    def chave(l):
        codigo = l.linha if hasattr(l, "linha") else l["linha"]
        secao, ordem, _nivel = LAYOUT_LINHAS.get(codigo, ("~desconhecida", 999, 1))
        return (ORDEM_SECOES.index(secao) if secao in ORDEM_SECOES else 999, ordem)
    return sorted(linhas, key=chave)


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

    linhas.append(LinhaApuracaoPC(
        "2", "Total das Exclusões (débito)", Decimal("0"), Decimal("0"), manual=True,
        detalhe={"nota": "Alíquota zero/monofásica/isenta já saem líquidas do valor_pis/valor_cofins de "
                          "cada item (via CST) — só falta aqui o que o CST não cobre (ICMS destacado, ICMS "
                          "ST, exportação), ver metodologia."},
    ))
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

    linhas.append(LinhaApuracaoPC(
        "6", "Total das Exclusões (crédito)", Decimal("0"), Decimal("0"), manual=True,
        detalhe={"nota": "Idem à linha 2 — falta só o que o CST não cobre (IPI, ICMS destacado, "
                          "exportação), ver metodologia."},
    ))
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
