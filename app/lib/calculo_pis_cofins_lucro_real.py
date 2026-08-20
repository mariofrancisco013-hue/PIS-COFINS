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

1. **Grupos "1.4 — Outras Saídas" e "5.8 — Outras Entradas" excluídos inteiros da base** (revisado em
   19/08/2026, 2ª vez, no mesmo dia): a primeira versão desta exclusão usava a coluna "Outras" da Rotina 1024
   (6ª coluna numérica de cada linha de CFOP, `resumo_1024_pc.valor_outras`) — mas isso exigia reimportar com
   "substituir" toda competência já lançada antes da migração 007 pra não ficar zerada. O usuário pediu pra
   simplificar: em vez de depender do PDF de novo, as linhas "2.5" (débito/saída) e "6.7" (crédito/entrada)
   passam a REPLICAR o próprio valor bruto já calculado das linhas "1.4"/"5.8" (mesmo `base_total`) — e o
   grupo inteiro (1.4 ou 5.8) deixa de contribuir com PIS/COFINS na base líquida (`base_liquida` forçada a
   zero em `calcular_apuracao_pc`, dentro do loop de `GRUPOS_DEBITO`/`GRUPOS_CREDITO`). "1.4"/"5.8" continuam
   exibindo o valor bruto normalmente (informativo, não desaparecem da tela); "2.5"/"6.7" só espelham esse
   mesmo número como exclusão. `resumo_1024_pc.valor_outras` continua existindo na tabela (migração 007) e
   ainda é usado em `conferencia_1024_x_1096` (auditoria CFOP a CFOP, sem efeito na apuração), mas não é mais
   lido dentro de `_base_por_grupo`.
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

# --- Lei Complementar 224/2025 — incidência residual sobre produtos isentos (20/08/2026, tabela desde a
# migração 009) ------------------------------------------------------------------------------------------
# Mesmo conceito do módulo Presumido, mesma tabela `ncms_lc224_pc` (compartilhada entre os dois regimes,
# distinguida pela coluna `regime`) — dentro dos itens de SAÍDA com CST 6/7 (que hoje entram inteiros na
# exclusão "2.7"), os que têm um NCM cadastrado ali passam a ter uma base de cálculo própria (o próprio
# Valor Contábil do item), tributada às alíquotas cadastradas (por NCM). Até 20/08/2026 (mais cedo no mesmo
# dia) a lista de NCMs e as alíquotas estavam fixas no código — pedido do usuário: "vira fonte do cálculo
# (editável)" direto no Supabase, sem precisar mexer em código/reimplantar o app.
REGIME_LC224 = "real"


def _variantes_ncm(ncm: str) -> set:
    """{variantes de texto} pra casar o NCM independente de zero à esquerda — ver mesma função no módulo
    Presumido (`calculo_pis_cofins_lucro_presumido.py`) para a explicação completa: `importacao_pc.py` grava
    `relatorio_pc_itens.ncm` como `str(int(v))` quando a célula do Excel é numérica pura, o que derruba
    zeros à esquerda (ex.: "09012100" vira "9012100")."""
    n = ncm.strip()
    variantes = {n}
    sem_zeros = n.lstrip("0") or "0"
    variantes.add(sem_zeros)
    if len(sem_zeros) <= 8:
        variantes.add(sem_zeros.zfill(8))
    return variantes


def _carregar_ncms_lc224(session):
    """{variante_ncm: (aliq_pis, aliq_cofins)} para todo NCM ativo cadastrado em `ncms_lc224_pc` para o
    regime Real — ver mesma função no módulo Presumido."""
    rows = session.execute(text("""
        select ncm, aliq_pis, aliq_cofins from ncms_lc224_pc where regime = :regime and ativo = true
    """), {"regime": REGIME_LC224}).mappings().all()
    lookup = {}
    for r in rows:
        par = (_dec(r["aliq_pis"]), _dec(r["aliq_cofins"]))
        for v in _variantes_ncm(str(r["ncm"])):
            lookup[v] = par
    return lookup

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
SECAO_LC224 = "4 — Produtos Isentos com Incidência Residual (LC 224/2025)"
SECAO_CREDITO = "5 — Crédito (Entrada)"
SECAO_EXCLUSOES_CREDITO = "6 — Exclusões do Crédito"
SECAO_SALDO_ANTERIOR = "8 — Saldo do Período Anterior"
SECAO_RESULTADO = "Resultado da Apuração"

ORDEM_SECOES = [
    SECAO_DEBITO, SECAO_EXCLUSOES_DEBITO, SECAO_FINANCEIRAS, SECAO_LC224, SECAO_CREDITO, SECAO_EXCLUSOES_CREDITO,
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
    "4": (SECAO_LC224, 0, 0),
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
    # (nota) linha "4" (LC 224/2025) mapeada acima, junto de "3".
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


def _base_por_grupo(resumo_1024, tipo_operacao, grupo, exclusao_cst_por_cfop, icms_correto_por_cfop):
    """Soma valor_contábil (bruto) e valor_contábil − ICMS_correto − exclusão_cst (líquido) de todas as
    linhas do resumo_1024_pc (já somando todas as filiais da competência) cujo CFOP pertence a este grupo.
    Devolve (base_bruta, base_liquida, detalhe_por_cfop) — o líquido é o que efetivamente entra no PIS/COFINS
    (base_liquida × alíquota); o bruto é só para exibir a "Receita" antes das exclusões, pra ficar visível na
    tela que as linhas 2.x/6.x realmente saem da base bruta.

    CORRIGIDOS DOIS BUGS em 20/08/2026 (ver seção "Bug real..." na metodologia do Presumido, mesma causa
    raiz aplicada aqui — usuário pediu pra ajustar o Real também depois de confirmar com dados reais no
    Presumido):

    1. **ICMS agregado por CFOP inteiro causava duplo desconto.** Antes: `icms = r["valor_icms"]` (Rotina
       1024, por linha de resumo_1024 — que já soma TODOS os itens daquele CFOP/filial, inclusive os com CST
       70/71/74 (entrada) ou 6/7 (saída)). Como esses mesmos itens também têm o Valor Contábil INTEIRO deles
       excluído por `exclusao_cst_por_cfop`, o ICMS embutido nesse valor contábil era descontado duas vezes.
       Agora usa `icms_correto_por_cfop` (ver `_somar_icms_nao_excluido_por_cfop`), que soma
       `relatorio_pc_itens.valor_nao_tributado` só dos itens SEM CST excluído — por identidade do próprio
       Winthor (`Vl.Tributado = Vl.Contábil − Vl.Não Tributado`, confirmada item a item contra um relatório
       de conferência oficial no módulo Presumido — mesmo formato de relatório, entrada/saída), essa coluna
       já É o ICMS do item quando ele não é excluído.
    2. **Exclusão de CST multiplicada pelo número de filiais.** `resumo_1024_pc` tem UMA LINHA POR (FILIAL,
       CFOP) — o loop antigo aplicava `exclusao_cst_por_cfop.get(cfop)` (um total já somado entre TODAS as
       filiais) a CADA linha de filial que batia com aquele CFOP, então um CFOP reportado por 3 filiais tinha
       sua exclusão de CST subtraída 3 vezes na base líquida. Agora o Valor Contábil é agregado por CFOP
       PRIMEIRO (somando todas as filiais), e cada exclusão (ICMS correto e CST) é aplicada só UMA VEZ por
       CFOP, do mesmo jeito que já é feito no módulo Presumido."""
    contabil_por_cfop = {}
    for r in resumo_1024:
        if r["tipo_operacao"] != tipo_operacao or r["grupo"] != grupo:
            continue
        contabil_por_cfop[r["cfop"]] = contabil_por_cfop.get(r["cfop"], Decimal("0")) + _dec(r["valor_contabil"])

    base_bruta = Decimal("0")
    base_liquida = Decimal("0")
    det = {}
    for cfop, contabil in contabil_por_cfop.items():
        icms = icms_correto_por_cfop.get(cfop, Decimal("0"))
        exc_cst = exclusao_cst_por_cfop.get(cfop, Decimal("0"))
        liquido_item = contabil - icms - exc_cst
        base_bruta += contabil
        base_liquida += liquido_item
        det[cfop] = liquido_item
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


def _somar_icms_nao_excluido_por_cfop(session, competencia_id, tipo_operacao, csts_excluidos):
    """{cfop: Decimal} com o ICMS destacado (`relatorio_pc_itens.valor_nao_tributado`) dos itens de
    `tipo_operacao` cujo CST NÃO está em `csts_excluidos`, somado entre todas as filiais — NOVO em
    20/08/2026, ver docstring de `_base_por_grupo` para a explicação completa do bug que isso corrige.
    Extrapolado do que foi confirmado com dados reais no módulo Presumido (saída, CST 6/7): a identidade
    `Vl.Tributado = Vl.Contábil − Vl.Não Tributado` é uma propriedade do próprio formato do relatório
    "Analítico" do Winthor (mesmo gerador para Entrada e Saída, qualquer regime) — não foi reconfirmada
    independentemente aqui para Entrada/CST 70-71-74, mas a mecânica do relatório é a mesma; vale re-
    conferir contra um relatório de conferência real de Entrada antes de confiar 100% se algo não bater."""
    placeholders = ", ".join(f":c{i}" for i in range(len(csts_excluidos)))
    params = {"cid": competencia_id, "tipo": tipo_operacao}
    params.update({f"c{i}": c for i, c in enumerate(csts_excluidos)})
    rows = session.execute(text(f"""
        select cfop, sum(valor_nao_tributado) as valor
        from relatorio_pc_itens
        where competencia_id = :cid and tipo_operacao = :tipo and cst not in ({placeholders})
        group by cfop
    """), params).mappings().all()
    return {r["cfop"]: _dec(r["valor"]) for r in rows}


def _somar_lc224_saida_por_cfop_ncm(session, competencia_id):
    """[{cfop, ncm, valor}] Valor Contábil (Relatório 1096, saída) agrupado por CFOP+NCM, só itens CST 6/7
    (excluídos em "2.7") — casado depois, em Python, contra o lookup de `_carregar_ncms_lc224` (mesma
    mecânica do módulo Presumido — não dá pra filtrar por NCM direto no SQL porque cada NCM pode ter uma
    alíquota diferente cadastrada, e variantes de zero à esquerda precisam ser casadas em Python)."""
    placeholders_cst = ", ".join(f":c{i}" for i in range(len(CSTS_EXCLUSAO_SAIDA)))
    params = {"cid": competencia_id}
    params.update({f"c{i}": c for i, c in enumerate(CSTS_EXCLUSAO_SAIDA)})
    rows = session.execute(text(f"""
        select cfop, ncm, sum(valor_contabil) as valor
        from relatorio_pc_itens
        where competencia_id = :cid and tipo_operacao = 'saida'
          and cst in ({placeholders_cst}) and ncm is not null
        group by cfop, ncm
    """), params).mappings().all()
    return [dict(r) for r in rows]


def calcular_apuracao_pc(session, competencia_id: int) -> list[LinhaApuracaoPC]:
    """Calcula as linhas 1.x-11.x da apuração PIS/COFINS Lucro Real a partir da Rotina 1024 (fonte primária,
    somando todas as filiais da competência/grupo). Não grava no banco — ver salvar_apuracao_pc."""

    resumo_1024 = session.execute(text("""
        select r.tipo_operacao, r.cfop, cpe.grupo, r.valor_contabil, r.valor_icms, r.valor_outras
        from resumo_1024_pc r
        join cfop_pis_cofins_efetivo cpe on cpe.codigo = r.cfop
        where r.competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    def _somar_exclusao_cst_escopada(tipo_operacao, grupos, valor_por_cfop):
        # Nome mantido por compatibilidade (usado desde 19/08/2026 só pra CST), mas genérico: soma qualquer
        # {cfop: Decimal} restrito aos CFOPs que de fato aparecem em resumo_1024 dentro desses grupos — mesma
        # regra aplicada dentro de _base_por_grupo, aqui só pro total de exibição (2.3/2.7/6.4/6.5) bater com
        # o que foi realmente subtraído da base, e não com a soma bruta de valor_por_cfop (que pode incluir
        # CFOPs sem Rotina 1024 importada nesta competência/filial). Desde 20/08/2026 também usada para o
        # ICMS correto (icms_correto_saida/entrada), não só para a exclusão de CST.
        cfops_do_grupo = {r["cfop"] for r in resumo_1024 if r["tipo_operacao"] == tipo_operacao and r["grupo"] in grupos}
        return sum((v for cfop, v in valor_por_cfop.items() if cfop in cfops_do_grupo), Decimal("0"))

    # Exclusão por CST (19/08/2026) — Valor Contábil dos itens do 1096 com CST 70/71/74 (entrada) / 6/7
    # (saída), agrupado por CFOP, calculado uma vez aqui e reusado tanto dentro de _base_por_grupo (embutido
    # na base líquida de cada grupo) quanto nos totais de exibição das linhas 6.5/2.7 abaixo.
    exclusao_cst_entrada = _somar_exclusao_cst_por_cfop(session, competencia_id, "entrada", CSTS_EXCLUSAO_ENTRADA)
    exclusao_cst_saida = _somar_exclusao_cst_por_cfop(session, competencia_id, "saida", CSTS_EXCLUSAO_SAIDA)
    # ICMS correto (20/08/2026, ver docstring de _base_por_grupo) — substitui resumo_1024_pc.valor_icms
    # dentro do cálculo da base líquida, pra não descontar duas vezes o ICMS dos itens já excluídos por CST.
    icms_correto_entrada = _somar_icms_nao_excluido_por_cfop(session, competencia_id, "entrada", CSTS_EXCLUSAO_ENTRADA)
    icms_correto_saida = _somar_icms_nao_excluido_por_cfop(session, competencia_id, "saida", CSTS_EXCLUSAO_SAIDA)

    linhas: list[LinhaApuracaoPC] = []

    # --- débito (saída) ---
    debito_pis_total = Decimal("0")
    debito_cofins_total = Decimal("0")
    debito_base_bruta_total = Decimal("0")   # soma de Valor Contábil (antes de excluir o ICMS)
    debito_base_liquida_total = Decimal("0")  # = base bruta - ICMS - Outras - CST 6/7 — é o que vira PIS/COFINS
    outras_bruta_saida = Decimal("0")  # = valor bruto do grupo "1.4" (ver nota abaixo em "2.5")
    for grupo, descricao in GRUPOS_DEBITO.items():
        base_bruta, base_liquida, det = _base_por_grupo(resumo_1024, "saida", grupo, exclusao_cst_saida,
                                                          icms_correto_saida)
        if grupo == "1.4":
            # "1.4 Outras Saídas" (catch-all de CFOP da Rotina 1024) — pedido do usuário em 19/08/2026, 2ª
            # revisão: a exclusão desse grupo NÃO depende mais da coluna "Outras" do PDF (valor_outras, que
            # exigiria reimportar toda competência já lançada com "substituir" pra ficar correta) — em vez
            # disso, o grupo "1.4" inteiro é excluído da base líquida (base_liquida = 0, não gera PIS/COFINS
            # nenhum), e seu valor BRUTO (o mesmo que a própria linha "1.4" exibe) é replicado como o valor
            # da linha "2.5" — mesmo número dos dois lados, por definição. base_bruta continua sendo somada
            # normalmente em debito_base_bruta_total/exibida em "1.4", só a base líquida (o que gera tributo)
            # é zerada.
            outras_bruta_saida = base_bruta
            base_liquida = Decimal("0")
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

    icms_excluido_saida = _somar_exclusao_cst_escopada("saida", GRUPOS_DEBITO.keys(), icms_correto_saida)
    cst_excluido_saida = _somar_exclusao_cst_escopada("saida", GRUPOS_DEBITO.keys(), exclusao_cst_saida)
    total_exclusoes_debito = icms_excluido_saida + outras_bruta_saida + cst_excluido_saida

    for linha, descricao in LINHAS_PENDENTES_DEBITO.items():
        linhas.append(LinhaApuracaoPC(linha, descricao, Decimal("0"), Decimal("0"), manual=True))

    linhas.append(LinhaApuracaoPC(
        "2.3", "(-) ICMS Apuração - Destacado Saídas", Decimal("0"), Decimal("0"), manual=False,
        detalhe={
            "base_total": str(icms_excluido_saida),
            "nota": "CORRIGIDO em 20/08/2026: soma de relatorio_pc_itens.valor_nao_tributado (Relatório "
                    "1096, saída) dos itens que NÃO são CST 6/7, todas as filiais — já é, item a item, o "
                    "ICMS destacado de cada item com direito a débito. Antes somava valor_icms da Rotina "
                    "1024 por CFOP inteiro (inclusive itens CST 6/7), descontando o ICMS deles duas vezes "
                    "junto com a linha \"2.7\" — ver metodologia (\"Bug real encontrado...\").",
            "icms_destacado_saida_total": str(icms_excluido_saida),
        },
    ))
    linhas.append(LinhaApuracaoPC(
        "2.5", "(-) Outras Saídas (Rotina 1024, coluna \"Outras\")", Decimal("0"), Decimal("0"), manual=False,
        detalhe={
            "base_total": str(outras_bruta_saida),
            "nota": "Réplica do valor bruto da linha \"1.4 — Outras Saídas\" — pedido do usuário em "
                    "19/08/2026 (2ª revisão): o grupo \"1.4\" (catch-all de CFOP da Rotina 1024) é excluído "
                    "inteiro da base, não gera PIS/COFINS. \"1.4\" segue exibindo o valor bruto normalmente "
                    "(informativo); \"2.5\" mostra a mesma exclusão. Não depende mais da coluna \"Outras\" do "
                    "PDF (valor_outras) — essa não exigia mais reimportar a Rotina 1024 pra corrigir.",
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

    # --- Produtos Isentos com Incidência Residual (linha 4, LC 224/2025 — pedido do usuário em 20/08/2026,
    # mesmo conceito implementado primeiro no módulo Presumido; fonte = tabela `ncms_lc224_pc` desde a
    # migração 009). Base própria (Valor Contábil dos itens CST 6/7 cujo NCM está cadastrado ali) — esses
    # itens já estão inteiros dentro da exclusão "2.7", então isto não muda a base líquida de nenhum grupo
    # de débito; é somado só no final (debito_pis_total/debito_cofins_total), do mesmo jeito que Receitas
    # Financeiras (linha "3") acima. Alíquotas vêm por NCM da tabela (hoje todas iguais: PIS 0,165% / COFINS
    # 0,76% — 1/10 da alíquota cheia do regime não-cumulativo).
    ncms_lc224_lookup = _carregar_ncms_lc224(session)
    itens_lc224 = _somar_lc224_saida_por_cfop_ncm(session, competencia_id)
    cfops_debito_ativos = {
        r["cfop"] for r in resumo_1024 if r["tipo_operacao"] == "saida" and r["grupo"] in GRUPOS_DEBITO
    }
    base_lc224 = Decimal("0")
    pis_lc224 = Decimal("0")
    cofins_lc224 = Decimal("0")
    detalhe_lc224_ncm = {}
    for item in itens_lc224:
        if item["cfop"] not in cfops_debito_ativos:
            continue
        ncm_norm = str(item["ncm"]).strip()
        par = ncms_lc224_lookup.get(ncm_norm)
        if not par:
            continue
        aliq_pis_n, aliq_cofins_n = par
        valor = _dec(item["valor"])
        base_lc224 += valor
        pis_lc224 += valor * aliq_pis_n
        cofins_lc224 += valor * aliq_cofins_n
        detalhe_lc224_ncm[ncm_norm] = detalhe_lc224_ncm.get(ncm_norm, Decimal("0")) + valor
    pis_lc224 = pis_lc224.quantize(Decimal("0.01")) if base_lc224 > 0 else Decimal("0")
    cofins_lc224 = cofins_lc224.quantize(Decimal("0.01")) if base_lc224 > 0 else Decimal("0")
    linhas.append(LinhaApuracaoPC(
        "4", "Produtos Isentos com Incidência Residual - Lei Complementar 224/2025 (NCMs específicos)",
        pis_lc224, cofins_lc224,
        detalhe={
            "base_total": str(base_lc224),
            "base_liquida": str(base_lc224),
            "nota": "Base = Valor Contábil (Relatório 1096, saída) dos itens com CST 6/7 (já dentro da "
                    "exclusão '2.7') cujo NCM está cadastrado em ncms_lc224_pc (tabela editável no Supabase "
                    "desde 20/08/2026 — sql/009_ncms_lc224_pc.sql, substituiu a lista fixa que estava no "
                    "código). Só conta CFOPs ativos na Rotina 1024 desta competência dentro dos grupos de "
                    "débito (1.1/1.2/1.4/1.6), mesmo escopo de 2.3/2.7.",
            "base_por_ncm": {k: str(v) for k, v in detalhe_lc224_ncm.items()},
        },
    ))
    debito_pis_total += pis_lc224
    debito_cofins_total += cofins_lc224

    # --- crédito (entrada) ---
    credito_pis_total = Decimal("0")
    credito_cofins_total = Decimal("0")
    credito_base_bruta_total = Decimal("0")
    credito_base_liquida_total = Decimal("0")
    outras_bruta_entrada = Decimal("0")  # = valor bruto do grupo "5.8" (mesmo padrão de "1.4"/"2.5")
    for grupo, descricao in GRUPOS_CREDITO.items():
        base_bruta, base_liquida, det = _base_por_grupo(resumo_1024, "entrada", grupo, exclusao_cst_entrada,
                                                          icms_correto_entrada)
        if grupo == "5.8":
            # "5.8 Outras Entradas" — mesmo tratamento de "1.4"/"2.5" (ver nota lá): grupo inteiro excluído
            # da base líquida (não gera crédito de PIS/COFINS), valor bruto replicado na linha "6.7".
            outras_bruta_entrada = base_bruta
            base_liquida = Decimal("0")
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

    icms_excluido_entrada = _somar_exclusao_cst_escopada("entrada", GRUPOS_CREDITO.keys(), icms_correto_entrada)
    cst_excluido_entrada = _somar_exclusao_cst_escopada("entrada", GRUPOS_CREDITO.keys(), exclusao_cst_entrada)
    total_exclusoes_credito = icms_excluido_entrada + outras_bruta_entrada + cst_excluido_entrada

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
            "nota": "CORRIGIDO em 20/08/2026: soma de relatorio_pc_itens.valor_nao_tributado (Relatório "
                    "1096, entrada) dos itens que NÃO são CST 70/71/74, todas as filiais — já é, item a "
                    "item, o ICMS destacado de cada item com direito a crédito. Antes somava valor_icms da "
                    "Rotina 1024 por CFOP inteiro (inclusive itens CST 70/71/74), descontando o ICMS deles "
                    "duas vezes junto com a linha \"6.5\" — ver metodologia (\"Bug real encontrado...\").",
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
            "base_total": str(outras_bruta_entrada),
            "nota": "Réplica do valor bruto da linha \"5.8 — Outras Entradas\" — pedido do usuário em "
                    "19/08/2026 (2ª revisão): o grupo \"5.8\" (catch-all de CFOP da Rotina 1024) é excluído "
                    "inteiro da base, não gera crédito de PIS/COFINS. \"5.8\" segue exibindo o valor bruto "
                    "normalmente (informativo); \"6.7\" mostra a mesma exclusão. Não depende mais da coluna "
                    "\"Outras\" do PDF (valor_outras) — essa não exigia mais reimportar a Rotina 1024 pra "
                    "corrigir.",
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
    comparando PIS/COFINS: `1024` = (valor_contabil - ICMS_correto - exclusão_cst) × alíquota — MESMA base
    usada em calcular_apuracao_pc (ver `_base_por_grupo`). CORRIGIDO em 20/08/2026: `valor_icms` agregado do
    1024 (que inclui o ICMS dos itens já excluídos por CST) foi trocado por `_somar_icms_nao_excluido_por_
    cfop` (Relatório 1096, só itens não-excluídos) — senão a Conferência ficaria "confirmando" uma conta
    diferente da que a Apuração de fato faz (double-count de ICMS nos itens CST 70/71/74/6/7, ver
    metodologia). `valor_outras` continua fora da base (mesmo motivo de calcular_apuracao_pc: grupos "1.4"/
    "5.8" são zerados por inteiro, não usam mais essa coluna). `1096` = soma direta de valor_pis/valor_cofins
    dos itens. Não usa cfop_pis_cofins (mostra TODO CFOP encontrado, mesmo sem grupo) — o objetivo aqui é
    auditoria, não o cálculo da apuração."""
    linhas_1024 = session.execute(text("""
        select cfop, tipo_operacao, sum(valor_contabil) as valor_contabil, sum(valor_icms) as valor_icms,
               sum(valor_outras) as valor_outras
        from resumo_1024_pc where competencia_id = :cid
        group by cfop, tipo_operacao
    """), {"cid": competencia_id}).mappings().all()

    exclusao_cst_entrada = _somar_exclusao_cst_por_cfop(session, competencia_id, "entrada", CSTS_EXCLUSAO_ENTRADA)
    exclusao_cst_saida = _somar_exclusao_cst_por_cfop(session, competencia_id, "saida", CSTS_EXCLUSAO_SAIDA)
    icms_correto_entrada = _somar_icms_nao_excluido_por_cfop(session, competencia_id, "entrada", CSTS_EXCLUSAO_ENTRADA)
    icms_correto_saida = _somar_icms_nao_excluido_por_cfop(session, competencia_id, "saida", CSTS_EXCLUSAO_SAIDA)

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
        icms_correto = (icms_correto_entrada if r["tipo_operacao"] == "entrada" else icms_correto_saida).get(
            r["cfop"], Decimal("0")
        )
        base = _dec(r["valor_contabil"]) - icms_correto - exclusao_cst
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
