"""
Cálculo da apuração PIS/COFINS — Lucro Real, regime não-cumulativo (Leis nº 10.637/2002 e 10.833/2003).

Reproduz a estrutura da planilha em uso pelo usuário (`PIS-COFINS - LUCRO REAL.xls`, aba "PC").

METODOLOGIA (revisada em 14/08/2026 — ver `claude/metodologia-pis-cofins-lucro-real.md` no projeto Claude
"PIS/COFINS" para o histórico completo): a apuração é feita por GRUPO ECONÔMICO (CNPJ raiz — matriz +
filiais consolidadas), não mais por uma única empresa. A fonte PRIMÁRIA da base de cálculo é a Rotina 1024
(Livro RAICMS Modelo P9), importada uma vez por filial (ver `app/lib/importar_1024_pc.py`, tabela
`resumo_1024_pc`) — confirmado com o usuário: a base do PIS/COFINS por CFOP é

    base = Valor Contábil − Imposto Creditado/Debitado (ICMS destacado)

agrupada pelos mesmos grupos de CFOP que a planilha original usa (1.1/1.2/1.4/1.6 débito, 5.1/5.2/5.5/5.7/
5.8 crédito), somada entre TODAS as filiais do grupo na mesma competência, com PIS = base × 1,65% e COFINS =
base × 7,60%. Isso já embute a exclusão de ICMS destacado (linhas 2.3 no débito, 6.4 no crédito, da planilha
original) dentro da própria base — essa linha é calculada à parte só para exibição/conferência (ver
"base_total" no detalhe), não somada de novo em cima da base já líquida.

NOTA (18/08/2026): entre 14 e 18/08 esta versão chegou a excluir também a coluna "Isentas/Não Tributadas" da
Rotina 1024 (5ª coluna numérica de cada linha de CFOP) — tentativa de bater a Conferência 1024×1096 quando
apareceu divergência sistemática. Isso adicionou as linhas "2.5"/"6.5" com valor calculado de verdade. O
usuário decidiu reverter essa exclusão em 18/08/2026 ("não é necessária"): a base voltou a ser só Valor
Contábil − ICMS destacado, a linha "2.5" foi removida e "6.5" voltou a ser manual/pendente (como era antes
de 14/08 à noite).

O Relatório 1096 (Entrada/Saída, item a item) CONTINUA sendo importado, mas agora só para CONFERÊNCIA por
CFOP contra o resultado do 1024 (ver `conferencia_1024_x_1096`) e para a checagem de CST fora da tabela
oficial — não alimenta mais a apuração diretamente (isso é diferente da v1, de 14/08/2026 pela manhã, que
somava valor_pis/valor_cofins direto dos itens do 1096; motivo da mudança: o usuário esclareceu que o cálculo
correto exclui o ICMS destacado por CFOP via 1024, e quer o 1096 só como comparação — "o correto é pegar a
1024, vl contábil menos o valor do icms destacado ai tenho a base do pis e cofins... e comparo com a 1096").

ACHADO (14/08/2026, ainda válido): a planilha antiga tratava "5.2 (+) Energia Elétrica" como linha 100%
manual. No Relatório 1024 a Energia (CFOP 1253) aparece normalmente como qualquer outro CFOP de crédito —
esta versão trata 5.2 como grupo calculado (CFOP 1253), não mais manual.

LAYOUT: `LAYOUT_LINHAS`/`ORDEM_SECOES`/`ordenar_linhas_para_exibicao()` no fim deste arquivo são só de
apresentação (agrupamento/ordem/indentação da tela, pedido do usuário em 14/08/2026) — não mudam valor
calculado nenhum.

NOVAS EXCLUSÕES E RECEITAS FINANCEIRAS (19/08/2026 — pedido do usuário mostrando o print da aba "Receitas
Financeiras" da planilha antiga, migração `sql/007_exclusoes_e_receitas_financeiras_pc.sql`):

1. **"Outras" da Rotina 1024** (6ª coluna numérica de cada linha de CFOP, capturada pelo parser mas
   descartada desde a reversão de 18/08/2026 — ver `importar_1024_pc.py`) volta a ser gravada
   (`resumo_1024_pc.valor_outras`) e agora É excluída da base, junto com o ICMS — linhas "2.5" (débito/
   saída) e "6.7" (crédito/entrada), mesmo padrão de exibição que "2.3"/"6.4" (valor real, calculado,
   `manual=False`), embutida em `base_liquida` por CFOP dentro de `_base_por_grupo` (não é um ajuste avulso
   no total — é somada/subtraída CFOP a CFOP, exatamente como o ICMS já era, pra manter a mesma
   granularidade de arredondamento).
2. **CST 70/71/74 (entrada) e CST 6/7 (saída)** — a Rotina 1024 soma cada CFOP inteiro, sem olhar o CST dos
   itens que compõem aquele CFOP no Relatório 1096. Como alguns desses CFOPs (ex.: 1407/1551/1556, dentro do
   grupo 5.8 "Outras Entradas") podem conter itens com CST 70/71/74 — que por definição NÃO geram crédito/
   débito de PIS/COFINS —, a base ficava inflada por esses itens. Agora o Valor Contábil (bruto — mesma
   unidade que a Rotina 1024 usa, decisão do usuário: "somar valor contábil") desses itens do 1096 é somado
   por CFOP e subtraído do CFOP correspondente em `resumo_1024`, do mesmo jeito que o ICMS — SÓ para CFOPs
   que efetivamente aparecem na Rotina 1024 da competência (mesma limitação já existente na Conferência
   1024×1096: um CST-tagged item cujo CFOP não tem Rotina 1024 importada pra essa competência/filial não tem
   como ser excluído de uma base que nunca o incluiu). Decisão do usuário sobre onde encaixar na numeração:
   a linha "6.5" — que já existia zerada como "(-) Entradas Isentas da Contribuição", exatamente o que CST
   71/74 representam — passa a ser CALCULADA de verdade (deixa de estar em `LINHAS_PENDENTES_CREDITO`); o
   lado da saída não tinha um placeholder equivalente, então ganhou uma linha nova, "2.7".
3. **Receitas Financeiras (linha "3", Lei 8.426/2015, PIS 0,65%/COFINS 4%)** — antes sempre zerada/manual,
   agora calculada a partir de 6 subitens editáveis na tela (Ajustes Manuais), replicando o print da
   planilha antiga (3.1 Desconto Obtido, 3.2 Variação Monetária, 3.3 Rendimento de Aplicação, 3.4 Juros
   recebidos, 3.5 Multas recebidas, 3.6 Outras Receitas — ver `receitas_financeiras_pc.py`, tabela nova
   `receitas_financeiras_pc`, upsert por `(competencia_id, tipo)`). É DÉBITO (soma no que se paga, diferente
   dos lançamentos de Aluguéis/Depreciação que são crédito) — por isso entra em `debito_pis_total`/
   `debito_cofins_total` (usados no saldo final), mas DEPOIS da linha "1" já ter sido fechada, pra "1" (Total
   das Receitas Tributáveis) continuar mostrando só o total dos grupos de CFOP de mercadoria, como sempre
   mostrou — receitas financeiras é uma seção separada (3) na planilha original, nunca fez parte de "1".
"""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import text

from lib.receitas_financeiras_pc import (
    ALIQ_PIS_FINANCEIRAS, ALIQ_COFINS_FINANCEIRAS, TIPOS_RECEITA_FINANCEIRA, carregar_receitas_financeiras,
    calcular_pis_cofins as _calcular_pis_cofins_financeiras,
)

ALIQ_PIS = Decimal("0.0165")
ALIQ_COFINS = Decimal("0.0760")

# CSTs de PIS/COFINS que não geram crédito/débito (entrada: sem direito a crédito/isenção/sem incidência;
# saída: espelho — ver metodologia "Regras confirmadas" no projeto) — usados para excluir da base o valor
# desses itens do Relatório 1096 (ver _somar_exclusao_cst_por_cfop), decisão do usuário em 19/08/2026.
CSTS_EXCLUSAO_ENTRADA = (70, 71, 74)
CSTS_EXCLUSAO_SAIDA = (6, 7)

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
# de estender LANCAMENTOS_TIPO_PARA_LINHA / adicionar a soma correspondente aqui. 2.3/6.4 (ICMS destacado)
# NÃO estão mais aqui desde 14/08/2026 — já saem embutidas na base de cada grupo (Valor Contábil − ICMS),
# ver calcular_apuracao_pc.
LINHAS_PENDENTES_DEBITO = {
    "1.3": "Faturamento Bruto (Prestação de Serviços)",
    "1.5": "Receitas de Aluguel de Bens",
    "2.4": "(-) ICMS Substituição",
    "2.6": "(-) Exportação de Mercadorias para o Exterior",
}
LINHAS_PENDENTES_CREDITO = {
    "5.9": "Fretes SUPPLY LOG",
    "6.3": "(-) IPI",
    "6.6": "(-) Exportação de Mercadorias para o Exterior",
}
# "3" (Receitas Financeiras) e "6.5" (Entradas Isentas/Sem Direito a Crédito) saíram das listas acima em
# 19/08/2026 — deixaram de ser manuais/zeradas, agora são calculadas (ver calcular_apuracao_pc).

# Lançamentos manuais implementados nesta versão (Aluguéis + Depreciação) — ver lancamentos_manuais_pc.py
LANCAMENTO_TIPO_PARA_LINHA = {
    "aluguel_predio_credito": ("5.3", "Aluguéis pagos a PJ (Prédios)"),
    "aluguel_maquinas_credito": ("5.4", "Aluguéis pagos a PJ (Máquinas e Equipamentos)"),
    "depreciacao_credito": ("5.6", "Depreciações Máquinas e Equip. e Outros Bens do Ativo Imobilizado"),
}

# Layout de exibição — só de APRESENTAÇÃO (não entra no cálculo). Mapeia cada linha para (seção, ordem
# dentro da seção, nível de indentação: 0 = total/destaque, 1 = sub-item).
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

LAYOUT_LINHAS = {
    "1.1": (SECAO_DEBITO, 0, 1), "1.2": (SECAO_DEBITO, 1, 1), "1.3": (SECAO_DEBITO, 2, 1),
    "1.4": (SECAO_DEBITO, 3, 1), "1.5": (SECAO_DEBITO, 4, 1), "1.6": (SECAO_DEBITO, 5, 1),
    "1": (SECAO_DEBITO, 6, 0),
    # "2.5" (Outras Saídas, coluna "Outras" da Rotina 1024) e "2.7" (CST 6/7) são novas em 19/08/2026 —
    # inseridas na ordem entre as exclusões já existentes, sem renumerar 2.3/2.4/2.6 (evita quebrar
    # referência a linha já salva em apuracao_pc_linhas de competências antigas).
    "2.3": (SECAO_EXCLUSOES_DEBITO, 0, 1), "2.4": (SECAO_EXCLUSOES_DEBITO, 1, 1),
    "2.5": (SECAO_EXCLUSOES_DEBITO, 2, 1), "2.6": (SECAO_EXCLUSOES_DEBITO, 3, 1),
    "2.7": (SECAO_EXCLUSOES_DEBITO, 4, 1),
    "2": (SECAO_EXCLUSOES_DEBITO, 5, 0),
    "3": (SECAO_FINANCEIRAS, 0, 0),
    "5.1": (SECAO_CREDITO, 0, 1), "5.2": (SECAO_CREDITO, 1, 1), "5.3": (SECAO_CREDITO, 2, 1),
    "5.4": (SECAO_CREDITO, 3, 1), "5.5": (SECAO_CREDITO, 4, 1), "5.6": (SECAO_CREDITO, 5, 1),
    "5.7": (SECAO_CREDITO, 6, 1), "5.8": (SECAO_CREDITO, 7, 1), "5.9": (SECAO_CREDITO, 8, 1),
    "5": (SECAO_CREDITO, 9, 0),
    # "6.5" é reaproveitada em 19/08/2026 (antes zerada/manual, "Entradas Isentas da Contribuição" — vira o
    # cálculo real de CST 70/71/74). "6.7" (Outras Entradas, coluna "Outras" da Rotina 1024) é nova.
    "6.3": (SECAO_EXCLUSOES_CREDITO, 0, 1), "6.4": (SECAO_EXCLUSOES_CREDITO, 1, 1),
    "6.5": (SECAO_EXCLUSOES_CREDITO, 2, 1), "6.6": (SECAO_EXCLUSOES_CREDITO, 3, 1),
    "6.7": (SECAO_EXCLUSOES_CREDITO, 4, 1),
    "6": (SECAO_EXCLUSOES_CREDITO, 5, 0),
    "8.1": (SECAO_SALDO_ANTERIOR, 0, 1), "8.2": (SECAO_SALDO_ANTERIOR, 1, 1),
    "9.1": (SECAO_RESULTADO, 0, 0), "9.2": (SECAO_RESULTADO, 1, 0),
    "10.1": (SECAO_RESULTADO, 2, 1), "10.2": (SECAO_RESULTADO, 3, 1),
    "11.1": (SECAO_RESULTADO, 4, 0), "11.2": (SECAO_RESULTADO, 5, 0), "11.3": (SECAO_RESULTADO, 6, 0),
}


def ordenar_linhas_para_exibicao(linhas: list) -> list:
    """Ordena uma lista de linhas (objetos com atributo `.linha`, ou dicts com chave `linha`) na sequência
    de exibição da planilha — usar isso na tela em vez de `order by linha` (ordem de texto)."""
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


def _base_por_grupo(resumo_1024, tipo_operacao, grupo, exclusao_cst_por_cfop):
    """Soma valor_contábil (bruto) e valor_contábil − valor_icms − valor_outras − exclusão_cst (líquido) de
    todas as linhas do resumo_1024_pc (já somando todas as filiais da competência) cujo CFOP pertence a este
    grupo. Devolve (base_bruta, base_liquida, detalhe_por_cfop) — o líquido é o que efetivamente entra no
    PIS/COFINS (base_liquida × alíquota); o bruto é só para exibir a "Receita" antes das exclusões, pra
    ficar visível na tela que as linhas 2.x/6.x realmente saem da base bruta.

    `exclusao_cst_por_cfop` (novo em 19/08/2026) = {cfop: Decimal} com o Valor Contábil somado do Relatório
    1096 dos itens com CST 70/71/74 (entrada) ou 6/7 (saída) daquele CFOP — ver
    _somar_exclusao_cst_por_cfop. Embutida aqui, CFOP a CFOP, exatamente como o ICMS (valor_icms) e "Outras"
    (valor_outras) já eram/são — mantém a mesma granularidade de arredondamento (uma quantização por grupo,
    não uma por linha), em vez de subtrair um total avulso do resultado final."""
    base_bruta = Decimal("0")
    base_liquida = Decimal("0")
    det = {}
    for r in resumo_1024:
        if r["tipo_operacao"] != tipo_operacao or r["grupo"] != grupo:
            continue
        contabil = _dec(r["valor_contabil"])
        icms = _dec(r["valor_icms"])
        outras = _dec(r.get("valor_outras"))
        exc_cst = exclusao_cst_por_cfop.get(r["cfop"], Decimal("0"))
        liquido_item = contabil - icms - outras - exc_cst
        base_bruta += contabil
        base_liquida += liquido_item
        atual = det.get(r["cfop"], Decimal("0"))
        det[r["cfop"]] = atual + liquido_item
    return base_bruta, base_liquida, det


def _somar_exclusao_cst_por_cfop(session, competencia_id, tipo_operacao, csts):
    """{cfop: Decimal(soma de valor_contabil)} dos itens do Relatório 1096 desta competência (todas as
    filiais) com CST em `csts`, agrupado por CFOP — usado para excluir da base o valor de itens que, pela
    própria definição do CST (sem direito a crédito/isenção/sem incidência — CST 70/71/74 na entrada, 6/7 na
    saída), não deveriam gerar crédito/débito de PIS/COFINS, mesmo que o CFOP deles esteja dentro de um
    grupo que a Rotina 1024 soma inteiro. Decisão do usuário em 19/08/2026: somar o Valor Contábil (bruto),
    mesma unidade que a Rotina 1024 usa como base — não o Valor Tributado (que no 1096 já vem líquido do que
    o próprio CST exclui, e teria pouco ou nenhum efeito prático aqui)."""
    placeholders = ", ".join(f":c{i}" for i in range(len(csts)))
    params = {"cid": competencia_id, "tipo": tipo_operacao}
    params.update({f"c{i}": c for i, c in enumerate(csts)})
    rows = session.execute(text(f"""
        select cfop, sum(valor_contabil) as valor
        from relatorio_pc_itens
        where competencia_id = :cid and tipo_operacao = :tipo and cst in ({placeholders})
        group by cfop
    """), params).mappings().all()
    return {r["cfop"]: _dec(r["valor"]) for r in rows}


def calcular_apuracao_pc(session, competencia_id: int) -> list[LinhaApuracaoPC]:
    """Calcula as linhas 1.x-11.x da apuração PIS/COFINS Lucro Real a partir da Rotina 1024 (fonte primária,
    somando todas as filiais da competência/grupo). Não grava no banco — ver salvar_apuracao_pc."""

    resumo_1024 = session.execute(text("""
        select r.tipo_operacao, r.cfop, cpe.grupo, r.valor_contabil, r.valor_icms, r.valor_outras
        from resumo_1024_pc r
        join cfop_pis_cofins_efetivo cpe on cpe.codigo = r.cfop
        where r.competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    def _somar_exclusao(tipo_operacao, grupos, campo):
        return sum(
            (_dec(r[campo]) for r in resumo_1024 if r["tipo_operacao"] == tipo_operacao and r["grupo"] in grupos),
            Decimal("0"),
        )

    def _somar_exclusao_cst_escopada(tipo_operacao, grupos, exclusao_por_cfop):
        # Só conta o CFOP se ele de fato aparece em resumo_1024 dentro de um desses grupos — mesma regra
        # aplicada dentro de _base_por_grupo, aqui só para o total de exibição (linha 6.5/2.7) bater com o
        # que foi realmente subtraído da base, e não com a soma bruta de exclusao_por_cfop (que pode incluir
        # CFOPs sem Rotina 1024 importada nesta competência/filial — ver nota em _somar_exclusao_cst_por_cfop).
        cfops_do_grupo = {r["cfop"] for r in resumo_1024 if r["tipo_operacao"] == tipo_operacao and r["grupo"] in grupos}
        return sum((v for cfop, v in exclusao_por_cfop.items() if cfop in cfops_do_grupo), Decimal("0"))

    # Exclusão por CST (19/08/2026) — Valor Contábil dos itens do 1096 com CST 70/71/74 (entrada) / 6/7
    # (saída), agrupado por CFOP, calculado uma vez aqui e reusado tanto dentro de _base_por_grupo (embutido
    # na base líquida de cada grupo) quanto nos totais de exibição das linhas 6.5/2.7 abaixo.
    exclusao_cst_entrada = _somar_exclusao_cst_por_cfop(session, competencia_id, "entrada", CSTS_EXCLUSAO_ENTRADA)
    exclusao_cst_saida = _somar_exclusao_cst_por_cfop(session, competencia_id, "saida", CSTS_EXCLUSAO_SAIDA)

    linhas: list[LinhaApuracaoPC] = []

    # --- débito (saída) ---
    debito_pis_total = Decimal("0")
    debito_cofins_total = Decimal("0")
    debito_base_bruta_total = Decimal("0")   # soma de Valor Contábil (antes de excluir o ICMS)
    debito_base_liquida_total = Decimal("0")  # = base bruta - ICMS - Outras - CST 6/7 — é o que vira PIS/COFINS
    for grupo, descricao in GRUPOS_DEBITO.items():
        base_bruta, base_liquida, det = _base_por_grupo(resumo_1024, "saida", grupo, exclusao_cst_saida)
        soma_pis = (base_liquida * ALIQ_PIS).quantize(Decimal("0.01"))
        soma_cofins = (base_liquida * ALIQ_COFINS).quantize(Decimal("0.01"))
        linhas.append(LinhaApuracaoPC(grupo, descricao, soma_pis, soma_cofins, detalhe={
            "base_total": str(base_bruta),
            "base_liquida": str(base_liquida),
            "base_por_cfop": {str(k): str(v) for k, v in det.items()},
        }))
        debito_pis_total += soma_pis
        debito_cofins_total += soma_cofins
        debito_base_bruta_total += base_bruta
        debito_base_liquida_total += base_liquida

    icms_excluido_saida = _somar_exclusao("saida", GRUPOS_DEBITO.keys(), "valor_icms")
    outras_excluido_saida = _somar_exclusao("saida", GRUPOS_DEBITO.keys(), "valor_outras")
    cst_excluido_saida = _somar_exclusao_cst_escopada("saida", GRUPOS_DEBITO.keys(), exclusao_cst_saida)
    total_exclusoes_debito = icms_excluido_saida + outras_excluido_saida + cst_excluido_saida

    for linha, descricao in LINHAS_PENDENTES_DEBITO.items():
        linhas.append(LinhaApuracaoPC(linha, descricao, Decimal("0"), Decimal("0"), manual=True))

    linhas.append(LinhaApuracaoPC(
        "2.3", "(-) ICMS Apuração - Destacado Saídas", Decimal("0"), Decimal("0"), manual=False,
        detalhe={
            "base_total": str(icms_excluido_saida),
            "nota": "Valor de ICMS destacado nas saídas (soma de todas as filiais, Rotina 1024) — é o que sai "
                    "da Receita Bruta (linha 1.1 a 1.6) para chegar na Base de Cálculo líquida do PIS/COFINS.",
            "icms_destacado_saida_total": str(icms_excluido_saida),
        },
    ))
    linhas.append(LinhaApuracaoPC(
        "2.5", "(-) Outras Saídas (Rotina 1024, coluna \"Outras\")", Decimal("0"), Decimal("0"), manual=False,
        detalhe={
            "base_total": str(outras_excluido_saida),
            "nota": "Coluna \"Outras\" (6ª e última coluna numérica de cada linha de CFOP da Rotina 1024, "
                    "soma de todas as filiais) — pedido do usuário em 19/08/2026, mesmo tratamento do ICMS "
                    "destacado (2.3): sai da Receita Bruta para chegar na Base de Cálculo líquida.",
        },
    ))
    linhas.append(LinhaApuracaoPC(
        "2.7", "(-) Saídas com CST 6/7 (sem direito a crédito/isenção/sem incidência)",
        Decimal("0"), Decimal("0"), manual=False,
        detalhe={
            "base_total": str(cst_excluido_saida),
            "nota": "Valor Contábil (soma de todas as filiais) dos itens do Relatório 1096 com CST 6 ou 7 "
                    "nesta competência — esses CSTs não geram débito de PIS/COFINS, mas o CFOP deles pode "
                    "estar dentro de um grupo (1.1/1.2/1.4/1.6) que a Rotina 1024 soma inteiro; pedido do "
                    "usuário em 19/08/2026. Só considera CFOPs que aparecem na Rotina 1024 desta competência "
                    "(mesma limitação da Conferência 1024×1096).",
        },
    ))
    linhas.append(LinhaApuracaoPC(
        "2", "Total das Exclusões (débito)", Decimal("0"), Decimal("0"), manual=True,
        detalhe={
            "base_total": str(total_exclusoes_debito),
            "nota": "Soma de 2.3 (ICMS destacado) + 2.5 (Outras) + 2.7 (CST 6/7), todas calculadas via "
                    "Rotina 1024/Relatório 1096 — 2.4/2.6 seguem pendentes (fora do escopo do 1024/1096 "
                    "nesta versão), ver metodologia.",
        },
    ))
    linhas.append(LinhaApuracaoPC("1", "Total das Receitas Tributáveis (débito)",
                                   debito_pis_total, debito_cofins_total,
                                   detalhe={
                                       "base_total": str(debito_base_bruta_total),
                                       "base_liquida": str(debito_base_liquida_total),
                                   }))

    # --- Receitas Financeiras (linha 3, alíquota reduzida Lei 8.426/2015 — pedido do usuário em 19/08/2026)
    # Débito: soma no que se paga. Somada em debito_pis_total/debito_cofins_total DEPOIS da linha "1" já ter
    # sido fechada acima — "1" (Total das Receitas Tributáveis) continua só com os grupos de CFOP de
    # mercadoria, como sempre foi; Receitas Financeiras é a seção "3", separada, na planilha original.
    receitas_fin_valores = carregar_receitas_financeiras(session, competencia_id)
    base_financeiras = sum(receitas_fin_valores.values(), Decimal("0"))
    pis_financeiras, cofins_financeiras = _calcular_pis_cofins_financeiras(base_financeiras)
    linhas.append(LinhaApuracaoPC(
        "3", "Receitas Financeiras (alíquota reduzida 0,65%/4% — Lei 8.426/2015)",
        pis_financeiras, cofins_financeiras,
        detalhe={
            "base_total": str(base_financeiras),
            "base_liquida": str(base_financeiras),
            "subitens": {t: str(receitas_fin_valores[t]) for t in TIPOS_RECEITA_FINANCEIRA},
            "nota": "Base = soma dos 6 subitens lançados na aba Ajustes Manuais (3.1 a 3.6). PIS = base × "
                    "0,65%, COFINS = base × 4% (Lei 8.426/2015) — alíquota bem menor que a cheia do regime "
                    "não-cumulativo (1,65%/7,60%) usada no resto da apuração.",
        },
    ))
    debito_pis_total += pis_financeiras
    debito_cofins_total += cofins_financeiras

    # --- crédito (entrada) ---
    credito_pis_total = Decimal("0")
    credito_cofins_total = Decimal("0")
    credito_base_bruta_total = Decimal("0")
    credito_base_liquida_total = Decimal("0")
    for grupo, descricao in GRUPOS_CREDITO.items():
        base_bruta, base_liquida, det = _base_por_grupo(resumo_1024, "entrada", grupo, exclusao_cst_entrada)
        soma_pis = (base_liquida * ALIQ_PIS).quantize(Decimal("0.01"))
        soma_cofins = (base_liquida * ALIQ_COFINS).quantize(Decimal("0.01"))
        linhas.append(LinhaApuracaoPC(grupo, descricao, soma_pis, soma_cofins, detalhe={
            "base_total": str(base_bruta),
            "base_liquida": str(base_liquida),
            "base_por_cfop": {str(k): str(v) for k, v in det.items()},
        }))
        credito_pis_total += soma_pis
        credito_cofins_total += soma_cofins
        credito_base_bruta_total += base_bruta
        credito_base_liquida_total += base_liquida

    icms_excluido_entrada = _somar_exclusao("entrada", GRUPOS_CREDITO.keys(), "valor_icms")
    outras_excluido_entrada = _somar_exclusao("entrada", GRUPOS_CREDITO.keys(), "valor_outras")
    cst_excluido_entrada = _somar_exclusao_cst_escopada("entrada", GRUPOS_CREDITO.keys(), exclusao_cst_entrada)
    total_exclusoes_credito = icms_excluido_entrada + outras_excluido_entrada + cst_excluido_entrada

    # lançamentos manuais (aluguéis, depreciação) — não têm ICMS pra excluir, bruto = líquido
    lancamentos = session.execute(text("""
        select tipo, descricao, base_valor, valor_pis, valor_cofins
        from lancamentos_manuais_pc where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    for tipo, (linha, descricao) in LANCAMENTO_TIPO_PARA_LINHA.items():
        itens_tipo = [l for l in lancamentos if l["tipo"] == tipo]
        soma_pis = sum((_dec(l["valor_pis"]) for l in itens_tipo), Decimal("0"))
        soma_cofins = sum((_dec(l["valor_cofins"]) for l in itens_tipo), Decimal("0"))
        base_lancamentos = sum((_dec(l["base_valor"]) for l in itens_tipo), Decimal("0"))
        det = {
            "base_total": str(base_lancamentos),
            "base_liquida": str(base_lancamentos),
            "lancamentos": [{"descricao": l["descricao"], "base": str(l["base_valor"])} for l in itens_tipo],
        }
        linhas.append(LinhaApuracaoPC(linha, descricao, soma_pis, soma_cofins, detalhe=det))
        credito_pis_total += soma_pis
        credito_cofins_total += soma_cofins
        credito_base_bruta_total += base_lancamentos
        credito_base_liquida_total += base_lancamentos

    for linha, descricao in LINHAS_PENDENTES_CREDITO.items():
        linhas.append(LinhaApuracaoPC(linha, descricao, Decimal("0"), Decimal("0"), manual=True))

    linhas.append(LinhaApuracaoPC(
        "6.4", "(-) ICMS Apuração - Destacado Entradas", Decimal("0"), Decimal("0"), manual=False,
        detalhe={
            "base_total": str(icms_excluido_entrada),
            "nota": "Valor de ICMS destacado nas entradas (soma de todas as filiais, Rotina 1024) — é o que "
                    "sai da base bruta de crédito (linha 5.1 a 5.8) para chegar na Base de Cálculo líquida.",
            "icms_destacado_entrada_total": str(icms_excluido_entrada),
        },
    ))
    linhas.append(LinhaApuracaoPC(
        "6.5", "(-) Entradas com CST 70/71/74 (sem direito a crédito/isenção/sem incidência)",
        Decimal("0"), Decimal("0"), manual=False,
        detalhe={
            "base_total": str(cst_excluido_entrada),
            "nota": "Valor Contábil (soma de todas as filiais) dos itens do Relatório 1096 com CST 70, 71 ou "
                    "74 nesta competência — esses CSTs não geram crédito de PIS/COFINS, mas o CFOP deles pode "
                    "estar dentro de um grupo (5.1/5.2/5.5/5.7/5.8) que a Rotina 1024 soma inteiro; pedido do "
                    "usuário em 19/08/2026 — antes esta linha era manual/zerada (\"Entradas Isentas da "
                    "Contribuição\"), agora é calculada de verdade. Só considera CFOPs que aparecem na Rotina "
                    "1024 desta competência (mesma limitação da Conferência 1024×1096).",
        },
    ))
    linhas.append(LinhaApuracaoPC(
        "6.7", "(-) Outras Entradas (Rotina 1024, coluna \"Outras\")", Decimal("0"), Decimal("0"), manual=False,
        detalhe={
            "base_total": str(outras_excluido_entrada),
            "nota": "Coluna \"Outras\" (6ª e última coluna numérica de cada linha de CFOP da Rotina 1024, "
                    "soma de todas as filiais) — pedido do usuário em 19/08/2026, mesmo tratamento do ICMS "
                    "destacado (6.4): sai da base bruta de crédito para chegar na Base de Cálculo líquida.",
        },
    ))
    linhas.append(LinhaApuracaoPC(
        "6", "Total das Exclusões (crédito)", Decimal("0"), Decimal("0"), manual=True,
        detalhe={
            "base_total": str(total_exclusoes_credito),
            "nota": "Soma de 6.4 (ICMS destacado) + 6.5 (CST 70/71/74) + 6.7 (Outras), todas calculadas via "
                    "Rotina 1024/Relatório 1096 — 6.3/6.6 seguem pendentes, ver metodologia.",
        },
    ))
    linhas.append(LinhaApuracaoPC("5", "Total de Créditos", credito_pis_total, credito_cofins_total,
                                   detalhe={
                                       "base_total": str(credito_base_bruta_total),
                                       "base_liquida": str(credito_base_liquida_total),
                                   }))

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


# ==================================================================================================
# CONFERÊNCIA 1024 × 1096 — comparação por CFOP, só leitura (não grava nada, não afeta a apuração). Pedido
# do usuário em 14/08/2026: usar o 1096 pra comparar com o resultado do 1024, não mais como fonte de cálculo.
# ==================================================================================================
TOLERANCIA_CONFERENCIA = Decimal("1.00")  # diferença em R$ acima disso é sinalizada como divergência


def conferencia_1024_x_1096(session, competencia_id: int) -> list[dict]:
    """Uma linha por CFOP presente no 1024 e/ou no 1096 desta competência (todas as filiais somadas),
    comparando PIS/COFINS: `1024` = (valor_contabil - valor_icms - valor_outras - exclusão_cst) × alíquota —
    mesma base usada em calcular_apuracao_pc (atualizado em 19/08/2026 para incluir as mesmas exclusões
    novas: coluna "Outras" da Rotina 1024 e CST 70/71/74/6/7 do 1096 — senão a conferência passaria a
    divergir por definição para todo CFOP afetado por essas exclusões, mesmo quando os dados batem); `1096`
    = soma direta de valor_pis/valor_cofins dos itens. Não usa cfop_pis_cofins (mostra TODO CFOP encontrado,
    mesmo sem grupo) — o objetivo aqui é auditoria, não o cálculo da apuração."""
    linhas_1024 = session.execute(text("""
        select cfop, tipo_operacao, sum(valor_contabil) as valor_contabil, sum(valor_icms) as valor_icms,
               sum(valor_outras) as valor_outras
        from resumo_1024_pc where competencia_id = :cid
        group by cfop, tipo_operacao
    """), {"cid": competencia_id}).mappings().all()

    exclusao_cst_entrada = _somar_exclusao_cst_por_cfop(session, competencia_id, "entrada", CSTS_EXCLUSAO_ENTRADA)
    exclusao_cst_saida = _somar_exclusao_cst_por_cfop(session, competencia_id, "saida", CSTS_EXCLUSAO_SAIDA)

    linhas_1096 = session.execute(text("""
        select cfop, tipo_operacao, sum(valor_pis) as valor_pis, sum(valor_cofins) as valor_cofins
        from relatorio_pc_itens where competencia_id = :cid
        group by cfop, tipo_operacao
    """), {"cid": competencia_id}).mappings().all()
    por_cfop_1096 = {(r["cfop"], r["tipo_operacao"]): r for r in linhas_1096}

    vistos = set()
    resultado = []
    for r in linhas_1024:
        chave = (r["cfop"], r["tipo_operacao"])
        vistos.add(chave)
        exclusao_cst = (exclusao_cst_entrada if r["tipo_operacao"] == "entrada" else exclusao_cst_saida).get(
            r["cfop"], Decimal("0")
        )
        base = _dec(r["valor_contabil"]) - _dec(r["valor_icms"]) - _dec(r["valor_outras"]) - exclusao_cst
        pis_1024 = (base * ALIQ_PIS).quantize(Decimal("0.01"))
        cofins_1024 = (base * ALIQ_COFINS).quantize(Decimal("0.01"))
        r1096 = por_cfop_1096.get(chave)
        pis_1096 = _dec(r1096["valor_pis"]) if r1096 else None
        cofins_1096 = _dec(r1096["valor_cofins"]) if r1096 else None
        resultado.append(_linha_conferencia(r["cfop"], r["tipo_operacao"], pis_1024, cofins_1024, pis_1096, cofins_1096))

    for chave, r1096 in por_cfop_1096.items():
        if chave in vistos:
            continue
        resultado.append(_linha_conferencia(
            chave[0], chave[1], None, None, _dec(r1096["valor_pis"]), _dec(r1096["valor_cofins"]),
        ))

    resultado.sort(key=lambda r: (r["tipo_operacao"], r["cfop"]))
    return resultado


def _linha_conferencia(cfop, tipo_operacao, pis_1024, cofins_1024, pis_1096, cofins_1096):
    if pis_1024 is None:
        situacao = "Só no 1096 (sem Rotina 1024 para este CFOP)"
    elif pis_1096 is None:
        situacao = "Só no 1024 (sem item no Relatório 1096 para este CFOP)"
    else:
        diff = abs(pis_1024 - pis_1096) + abs(cofins_1024 - cofins_1096)
        situacao = "OK" if diff <= TOLERANCIA_CONFERENCIA else "Divergente"
    return {
        "cfop": cfop, "tipo_operacao": tipo_operacao,
        "pis_1024": pis_1024, "cofins_1024": cofins_1024,
        "pis_1096": pis_1096, "cofins_1096": cofins_1096,
        "diff_pis": (pis_1024 - pis_1096) if (pis_1024 is not None and pis_1096 is not None) else None,
        "diff_cofins": (cofins_1024 - cofins_1096) if (cofins_1024 is not None and cofins_1096 is not None) else None,
        "situacao": situacao,
    }
