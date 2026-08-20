"""
Cálculo da apuração PIS/COFINS — Lucro Presumido, regime CUMULATIVO (Lei nº 9.718/1998, art. 3º/8º — PIS
0,65% / COFINS 3,00% sobre o faturamento, sem direito a crédito de entrada).

Construído em 19/08/2026, reproduzindo a estrutura da aba "PC" da planilha `Apuração TERESINA
DISTRIBUIDORA 2026.xls` (primeiro grupo deste módulo — CNPJ 48.288.160/0001-04). Pedido do usuário: "mesmo
raciocínio de conferência com a 1096 e 1024" já usado no módulo Lucro Real (`calculo_pis_cofins_lucro_real.
py`) — reaproveita as MESMAS tabelas (`resumo_1024_pc`, `relatorio_pc_itens`, `apuracao_pc_linhas`,
`competencias` com `modulo='pis_cofins_lucro_presumido'`, já previsto no `check` da coluna desde o schema
inicial de 14/08/2026) e a MESMA infraestrutura de importação (`importacao_pc.py`, `importar_1024_pc.py` —
nenhuma dessas é regime-específica, já aceitam `modulo`/`regime_like` como parâmetro).

DIFERENÇAS-CHAVE em relação ao Lucro Real (confirmadas com o usuário em 19/08/2026):

1. **Só movimentação de SAÍDA compõe a receita** — regime cumulativo não gera crédito sobre compras. A
   única coisa do lado de ENTRADA que entra na conta é a Devolução de Venda (linha "1.2", ver abaixo) — não
   é "crédito", é uma dedução direta da receita bruta (o cliente devolveu, não houve venda).
2. **CST 6 e 7 (saída) = "Isentos"**, tratados como UMA exclusão só (linha "2.1") — decisão explícita do
   usuário ("os CSTs da saida, 6 e 7 como isentos"), mesmo quando a planilha antiga (aba PC) tinha duas
   linhas separadas ("2.1 Alíquota Zero" / "2.5 Isentas da Contribuição"). Não foi possível reconstruir com
   confiança a fórmula original de "2.1" da planilha antiga a partir dos dados brutos (não bate com nenhuma
   soma simples de CST/CFOP testada) — em vez de adivinhar, a versão nova usa a regra que o usuário deu por
   escrito: CST 6 + CST 7 do Relatório 1096 (saída), somados.
3. **PIS/COFINS é calculado UMA VEZ só, em cima da Base de Cálculo final** ("3" = "1" − "2") — diferente do
   Lucro Real, que calcula PIS/COFINS grupo a grupo (CFOP a CFOP) e soma. Aqui as linhas 1.x/2.x são só
   BASE (valor em R$, sem PIS/COFINS próprio) — bate com a estrutura da planilha antiga, cujas colunas "P"/
   "C" (linhas 53/54) só aparecem uma vez, depois da linha "3".
4. **Os grupos de CFOP NÃO usam a tabela compartilhada `cfop_pis_cofins`** (a mesma do Lucro Real) para
   decidir a classificação — usam listas fixas em Python (`CFOPS_1_1`, `CFOPS_1_4`, `CFOPS_1_2_DEVOLUCAO_
   VENDA` abaixo), extraídas e cruzadas contra a aba "PC" e a aba "CONTABIL" da planilha da Teresina. Motivo:
   `cfop_pis_cofins.codigo` é chave primária ÚNICA por CFOP (uma classificação só, compartilhada entre TODOS
   os grupos/regimes) — e pelo menos 3 CFOPs (5202, 5411, 6202) aparecem na aba CONTABIL da Teresina como
   "DEVOLUÇÃO"/"DEVOLUÇÕES DE COMPRAS", que é um conceito diferente do que já pode estar cadastrado pro
   Lucro Real (que tem sua própria linha "1.2 Devolução de Mercadoria de Compra"). Sem acesso ao banco de
   produção pra conferir o que já está cadastrado ali, usar listas fixas aqui evita qualquer risco de
   sobrescrever/colidir com a classificação já em uso pelo Lucro Real. O cadastro em `cfop_pis_cofins`
   continua sendo alimentado (migração `sql/008_lucro_presumido.sql`, só `insert ... on conflict do
   nothing`) para não gerar falsas inconsistências "CFOP sem grupo" na conferência do 1096 — mas o CÁLCULO
   em si não depende dele.

PONTOS EM ABERTO (deixados manuais/zerados nesta versão, mesmo padrão do Lucro Real — ver `LINHAS_
PENDENTES`):
- "1.3" Faturamento Bruto (Prestação de Serviços), "1.5" Receitas de Aluguel de Bens, "1.6" Demais Receitas
  Operacionais — sem CFOP/dado na planilha da Teresina (todos zerados nos 7 meses vistos).
- "2.2" Incidência da Contribuição Monofásica, "2.6" Exportação de Mercadorias para o Exterior — idem.
- "5.1"/"5.2" PERD/COMP — mesmo ponto em aberto do Lucro Real (saldo não encadeia entre competências ainda).

LINHA "3.1" — INCIDÊNCIA SOBRE PRODUTOS ISENTOS, LEI COMPLEMENTAR 224/2025 (20/08/2026): implementada a
partir de especificação dada diretamente pelo usuário (não mais adivinhada a partir da planilha antiga, ao
contrário do que o ponto em aberto anterior dizia). NCMs e alíquotas ficam na tabela `ncms_lc224_pc`
(migração `sql/009_ncms_lc224_pc.sql`, editável direto no Supabase — ver `_carregar_ncms_lc224`) desde
20/08/2026 (mais tarde no mesmo dia; a primeira versão tinha isso fixo no código) — ver a linha "3.1" em
`calcular_apuracao_pc_presumido`.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import text

ALIQ_PIS = Decimal("0.0065")
ALIQ_COFINS = Decimal("0.0300")

# CST de saída que o usuário definiu como "isentos" (linha "2.1") — juntos, uma exclusão só (pedido
# explícito em 19/08/2026, mesmo a planilha antiga separando em duas linhas "2.1"/"2.5" — ver docstring).
CSTS_ISENTOS_SAIDA = (6, 7)

# --- Lei Complementar 224/2025 — incidência residual sobre produtos isentos (20/08/2026, tabela desde a
# migração 009) ------------------------------------------------------------------------------------------
# Pedido do usuário: dentro dos itens de saída CST 6/7 (que hoje entram inteiros na exclusão "2.1"), os que
# têm um NCM cadastrado em `ncms_lc224_pc` passam a ter uma base de cálculo própria (o próprio Valor
# Contábil do item), tributada às alíquotas cadastradas ali (por NCM, por regime) — bem menores que a cheia
# do regime. Até 20/08/2026 (mais cedo no mesmo dia) essa lista e as alíquotas estavam fixas no código
# (`NCMS_LC224_2025_RAW`/`ALIQ_PIS_LC224`/`ALIQ_COFINS_LC224`) — pedido do usuário: "vira fonte do cálculo
# (editável)" — trocado por uma tabela no banco (ver `sql/009_ncms_lc224_pc.sql`), editável direto no
# Supabase (inserir/desativar NCM, mudar alíquota) sem precisar mexer em código nem reimplantar o app.
REGIME_LC224 = "presumido"


def _variantes_ncm(ncm: str) -> set:
    """{variantes de texto} para casar o NCM independente de zero à esquerda. `importacao_pc.py` grava
    `relatorio_pc_itens.ncm` como `str(int(v))` quando a célula do Excel é numérica pura — ou seja, um NCM
    como "09012100" perde o zero à esquerda e vira "9012100" no banco (confirmado lendo o código de
    importação). Gera a forma crua, sem zeros à esquerda, e com 8 dígitos (zero-padded), pra casar com
    qualquer uma das três convenções sem risco de colisão (NCM sempre tem 8 dígitos "de verdade")."""
    n = ncm.strip()
    variantes = {n}
    sem_zeros = n.lstrip("0") or "0"
    variantes.add(sem_zeros)
    if len(sem_zeros) <= 8:
        variantes.add(sem_zeros.zfill(8))
    return variantes


def _carregar_ncms_lc224(session):
    """{variante_ncm: (aliq_pis, aliq_cofins)} para todo NCM ativo cadastrado em `ncms_lc224_pc` para o
    regime Presumido — cada variante (crua/sem zero/zero-padded, ver `_variantes_ncm`) do mesmo NCM aponta
    para o mesmo par de alíquotas, pra casar com `relatorio_pc_itens.ncm` independente de zero à esquerda."""
    rows = session.execute(text("""
        select ncm, aliq_pis, aliq_cofins from ncms_lc224_pc where regime = :regime and ativo = true
    """), {"regime": REGIME_LC224}).mappings().all()
    lookup = {}
    for r in rows:
        par = (_dec(r["aliq_pis"]), _dec(r["aliq_cofins"]))
        for v in _variantes_ncm(str(r["ncm"])):
            lookup[v] = par
    return lookup

# --- Grupos de CFOP (listas fixas — ver item 4 da docstring do módulo) ---------------------------------
# "1.1 Faturamento Bruto (Mercadorias p/Revenda)" — cruzado contra a aba CONTABIL da Teresina, seção
# "RECEITAS DE REVENDA" (bate 100%, exceto 6120 que só aparece na aba PC/mês de maio — mantido).
CFOPS_1_1 = frozenset({5102, 5117, 5119, 5403, 5405, 6102, 6108, 6117, 6119, 6120, 6403, 7102})
# "1.4 Outras Saídas" — direto da aba PC (linhas de detalhe sob "1.4"), inclui CFOPs que a aba CONTABIL
# rotula como "DEVOLUÇÃO"/"BAIXA DE ESTOQUE"/"TRANSFERENCIA" mas que a própria planilha de apuração em uso
# soma dentro de "Outras Saídas" — segue o que a planilha realmente faz, não a etiqueta da aba CONTABIL.
CFOPS_1_4 = frozenset({5152, 5202, 5409, 5411, 5910, 5923, 5926, 5927, 5929, 5949, 6202, 6923})
# "1.2 Devolução de Venda" (ENTRADA — cliente devolvendo o que foi vendido) — bate exato contra a aba
# CONTABIL, seção "DEVOLUÇÃO DE VENDAS", e contra a aba PC (linhas de detalhe sob "1.2").
CFOPS_1_2_DEVOLUCAO_VENDA = frozenset({1202, 1411, 2202, 2411, 3202})

LINHAS_PENDENTES = {
    "1.3": "(+) Faturamento Bruto (Prestação de Serviços)",
    "1.5": "(+) Receitas de Aluguel de Bens",
    "1.6": "(+) Demais Receitas Operacionais",
    "2.2": "(-) Incidência da Contribuição Monofásica",
    "2.6": "(-) Exportação de Mercadorias para o Exterior",
    "5.1": "PERD/COMP - cumulativa PIS",
    "5.2": "PERD/COMP - cumulativa COFINS",
}

SECAO_RECEITAS = "1 — Receitas Tributáveis"
SECAO_EXCLUSOES = "2 — Exclusões"
SECAO_BASE = "3 — Base de Cálculo"
SECAO_CONTRIBUICAO = "Contribuição Apurada"
SECAO_RESULTADO = "Resultado da Apuração"

ORDEM_SECOES = [SECAO_RECEITAS, SECAO_EXCLUSOES, SECAO_BASE, SECAO_CONTRIBUICAO, SECAO_RESULTADO]

LAYOUT_LINHAS = {
    "1.1": (SECAO_RECEITAS, 0, 1), "1.3": (SECAO_RECEITAS, 1, 1), "1.4": (SECAO_RECEITAS, 2, 1),
    "1.5": (SECAO_RECEITAS, 3, 1), "1.6": (SECAO_RECEITAS, 4, 1), "1": (SECAO_RECEITAS, 5, 0),
    "2.1": (SECAO_EXCLUSOES, 0, 1), "2.2": (SECAO_EXCLUSOES, 1, 1), "2.3": (SECAO_EXCLUSOES, 2, 1),
    "1.2": (SECAO_EXCLUSOES, 3, 1), "2.6": (SECAO_EXCLUSOES, 4, 1), "2": (SECAO_EXCLUSOES, 5, 0),
    "3": (SECAO_BASE, 0, 0), "3.1": (SECAO_BASE, 1, 1),
    "P": (SECAO_CONTRIBUICAO, 0, 1), "C": (SECAO_CONTRIBUICAO, 1, 1),
    "4.1": (SECAO_RESULTADO, 0, 0), "4.2": (SECAO_RESULTADO, 1, 0),
    "5.1": (SECAO_RESULTADO, 2, 1), "5.2": (SECAO_RESULTADO, 3, 1),
    "6.1": (SECAO_RESULTADO, 4, 0), "6.2": (SECAO_RESULTADO, 5, 0), "7.3": (SECAO_RESULTADO, 6, 0),
}


def ordenar_linhas_para_exibicao(linhas: list) -> list:
    def chave(l):
        codigo = l.linha if hasattr(l, "linha") else l["linha"]
        secao, ordem, _nivel = LAYOUT_LINHAS.get(codigo, ("~desconhecida", 999, 1))
        return (ORDEM_SECOES.index(secao) if secao in ORDEM_SECOES else 999, ordem)
    return sorted(linhas, key=chave)


@dataclass
class LinhaApuracaoPresumido:
    linha: str
    descricao: str
    valor_pis: Decimal
    valor_cofins: Decimal
    manual: bool = False
    detalhe: dict = field(default_factory=dict)


def _dec(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def _arred(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def _somar_cst_isento_por_cfop(session, competencia_id):
    """{cfop: Decimal} com o Valor Contábil somado do Relatório 1096 (saída) dos itens com CST 6 ou 7 nesta
    competência — mesma mecânica de `_somar_exclusao_cst_por_cfop` do Lucro Real. Placeholders nomeados
    manualmente (:c0, :c1, ...) em vez de `cst in :csts` — texto puro do SQLAlchemy não expande um tuple
    sozinho num `in` (precisaria de `bindparam(expanding=True)`), então `in :csts` falha silenciosamente
    virando `in ?` com o tuple inteiro como um parâmetro só (já teste isso isoladamente antes de usar aqui)."""
    placeholders = ", ".join(f":c{i}" for i in range(len(CSTS_ISENTOS_SAIDA)))
    params = {"cid": competencia_id}
    params.update({f"c{i}": c for i, c in enumerate(CSTS_ISENTOS_SAIDA)})
    rows = session.execute(text(f"""
        select cfop, sum(valor_contabil) as valor
        from relatorio_pc_itens
        where competencia_id = :cid and tipo_operacao = 'saida' and cst in ({placeholders})
        group by cfop
    """), params).mappings().all()
    return {r["cfop"]: _dec(r["valor"]) for r in rows}


def _somar_icms_saida_nao_isento_por_cfop(session, competencia_id):
    """{cfop: Decimal} com o ICMS destacado que de fato pertence aos itens TRIBUTADOS de saída (CST de
    PIS/COFINS diferente de 6/7) — CORREÇÃO de 20/08/2026, ver seção "Bug real encontrado..." na
    metodologia. Fonte: `relatorio_pc_itens.valor_nao_tributado` (Relatório 1096, já importado, não precisa
    de relatório novo), que por identidade do próprio Winthor (`Vl.Tributado = Vl.Contábil − Vl.Não
    Tributado`, válida item a item) vale exatamente o ICMS destacado quando o item é tributado — confirmado
    contra o "Relatório de conferência PIS/COFINS e ICMS" (item a item, 26.399 itens, bateu ao centavo nos
    totais oficiais). Substitui a antiga soma de `resumo_1024_pc.valor_icms`: aquela soma é por CFOP
    INTEIRO (Rotina 1024 não separa ICMS por CST de PIS/COFINS) e inclui o ICMS dos itens CST 6/7 — que,
    somado à exclusão separada desses mesmos itens (`_somar_cst_isento_por_cfop`), descontava o ICMS deles
    DUAS VEZES (prova numérica real: CFOP 5102/filial F7/jul-2026, base menor em R$ 17.285,44 — exatamente o
    ICMS dos 643 itens isentos daquele CFOP/mês)."""
    placeholders = ", ".join(f":c{i}" for i in range(len(CSTS_ISENTOS_SAIDA)))
    params = {"cid": competencia_id}
    params.update({f"c{i}": c for i, c in enumerate(CSTS_ISENTOS_SAIDA)})
    rows = session.execute(text(f"""
        select cfop, sum(valor_nao_tributado) as valor
        from relatorio_pc_itens
        where competencia_id = :cid and tipo_operacao = 'saida' and cst not in ({placeholders})
        group by cfop
    """), params).mappings().all()
    return {r["cfop"]: _dec(r["valor"]) for r in rows}


def _somar_lc224_saida_por_cfop_ncm(session, competencia_id):
    """[{cfop, ncm, valor}] Valor Contábil (Relatório 1096, saída) agrupado por CFOP+NCM, só itens CST 6/7
    (isento) — casado depois, em Python, contra o lookup de `_carregar_ncms_lc224` (não dá pra filtrar por
    NCM direto no SQL porque cada NCM pode ter uma alíquota diferente cadastrada, e o SQL não sabe casar as
    variantes de zero à esquerda de `_variantes_ncm`)."""
    placeholders_cst = ", ".join(f":c{i}" for i in range(len(CSTS_ISENTOS_SAIDA)))
    params = {"cid": competencia_id}
    params.update({f"c{i}": c for i, c in enumerate(CSTS_ISENTOS_SAIDA)})
    rows = session.execute(text(f"""
        select cfop, ncm, sum(valor_contabil) as valor
        from relatorio_pc_itens
        where competencia_id = :cid and tipo_operacao = 'saida'
          and cst in ({placeholders_cst}) and ncm is not null
        group by cfop, ncm
    """), params).mappings().all()
    return [dict(r) for r in rows]


def calcular_apuracao_pc_presumido(session, competencia_id: int) -> list[LinhaApuracaoPresumido]:
    """Calcula as linhas 1.x-7.3 da apuração PIS/COFINS Lucro Presumido a partir da Rotina 1024 (saída, só
    para o Valor Contábil bruto das linhas 1.1/1.4) + Relatório 1096 (saída — exclusão de CST isento E,
    desde 20/08/2026, também o ICMS destacado dos itens tributados, ver `_somar_icms_saida_nao_isento_por_
    cfop`) — não grava no banco, ver `salvar_apuracao_pc_presumido`. Mesma tabela `apuracao_pc_linhas` do
    Lucro Real (a `competencia_id` já identifica o módulo via `competencias.modulo`)."""
    resumo_1024 = session.execute(text("""
        select tipo_operacao, cfop, valor_contabil, valor_icms
        from resumo_1024_pc where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    cst_isento_por_cfop = _somar_cst_isento_por_cfop(session, competencia_id)
    icms_nao_isento_por_cfop = _somar_icms_saida_nao_isento_por_cfop(session, competencia_id)
    ncms_lc224_lookup = _carregar_ncms_lc224(session)
    itens_lc224 = _somar_lc224_saida_por_cfop_ncm(session, competencia_id)

    def _soma_bruta(tipo_operacao, cfops):
        return sum(
            (_dec(r["valor_contabil"]) for r in resumo_1024
             if r["tipo_operacao"] == tipo_operacao and r["cfop"] in cfops),
            Decimal("0"),
        )

    def _soma_icms(tipo_operacao, cfops):
        return sum(
            (_dec(r["valor_icms"]) for r in resumo_1024
             if r["tipo_operacao"] == tipo_operacao and r["cfop"] in cfops),
            Decimal("0"),
        )

    def _soma_isento_escopado(cfops):
        # Só conta CST isento de CFOPs que de fato aparecem no 1024 desta competência DENTRO do grupo — mesma
        # regra do Lucro Real (evita contar CST 6/7 de um CFOP cujo grupo nem está ativo/importado ainda).
        cfops_ativos = {r["cfop"] for r in resumo_1024 if r["tipo_operacao"] == "saida" and r["cfop"] in cfops}
        return sum((v for cfop, v in cst_isento_por_cfop.items() if cfop in cfops_ativos), Decimal("0"))

    def _soma_icms_saida_nao_isento_escopado(cfops):
        # Mesmo escopo de `_soma_isento_escopado` acima (só CFOPs ativos no 1024 desta competência) — usa o
        # ICMS correto (só dos itens tributados, fonte 1096) em vez do valor_icms agregado do 1024.
        cfops_ativos = {r["cfop"] for r in resumo_1024 if r["tipo_operacao"] == "saida" and r["cfop"] in cfops}
        return sum((v for cfop, v in icms_nao_isento_por_cfop.items() if cfop in cfops_ativos), Decimal("0"))

    def _calcular_lc224_escopado(cfops):
        # Mesmo escopo das outras somas por CFOP (só CFOPs que aparecem na Rotina 1024 desta competência).
        # Casa cada item contra o lookup por NCM (com alíquotas próprias por NCM, ver _carregar_ncms_lc224) —
        # itens cujo NCM não está cadastrado em ncms_lc224_pc são ignorados (não fazem parte da LC 224/2025).
        cfops_ativos = {r["cfop"] for r in resumo_1024 if r["tipo_operacao"] == "saida" and r["cfop"] in cfops}
        base_total = Decimal("0")
        pis_total = Decimal("0")
        cofins_total = Decimal("0")
        detalhe_por_ncm = {}
        for item in itens_lc224:
            if item["cfop"] not in cfops_ativos:
                continue
            ncm_norm = str(item["ncm"]).strip()
            par = ncms_lc224_lookup.get(ncm_norm)
            if not par:
                continue
            aliq_pis_n, aliq_cofins_n = par
            valor = _dec(item["valor"])
            base_total += valor
            pis_total += valor * aliq_pis_n
            cofins_total += valor * aliq_cofins_n
            detalhe_por_ncm[ncm_norm] = detalhe_por_ncm.get(ncm_norm, Decimal("0")) + valor
        return base_total, pis_total, cofins_total, detalhe_por_ncm

    linhas: list[LinhaApuracaoPresumido] = []

    # --- 1 — Receitas Tributáveis (só saída; bruto, sem descontar ICMS/isentos aqui — igual à planilha
    # original, onde "1" é a Receita Bruta e as exclusões saem inteiras na seção "2") ---
    base_1_1 = _soma_bruta("saida", CFOPS_1_1)
    base_1_4 = _soma_bruta("saida", CFOPS_1_4)
    linhas.append(LinhaApuracaoPresumido("1.1", "(+) Faturamento Bruto (Mercadorias p/Revenda)",
                                          Decimal("0"), Decimal("0"), detalhe={"base_total": str(base_1_1)}))
    linhas.append(LinhaApuracaoPresumido("1.4", "(+) Outras Saídas", Decimal("0"), Decimal("0"),
                                          detalhe={"base_total": str(base_1_4)}))
    for linha in ("1.3", "1.5", "1.6"):
        linhas.append(LinhaApuracaoPresumido(linha, LINHAS_PENDENTES[linha], Decimal("0"), Decimal("0"),
                                              manual=True))
    total_receitas = base_1_1 + base_1_4
    linhas.append(LinhaApuracaoPresumido("1", "1 - Totais das Receitas Tributáveis", Decimal("0"),
                                          Decimal("0"), detalhe={"base_total": str(total_receitas)}))

    # --- 2 — Exclusões ---
    isentos_saida = _soma_isento_escopado(CFOPS_1_1 | CFOPS_1_4)
    linhas.append(LinhaApuracaoPresumido(
        "2.1", "(-) Saídas Isentas / Alíquota Zero (CST 6 e 7)", Decimal("0"), Decimal("0"),
        detalhe={
            "base_total": str(isentos_saida),
            "nota": "Soma do Valor Contábil (Relatório 1096, saída) dos itens com CST 6 (alíquota zero) ou "
                    "CST 7 (isenta da contribuição) — pedido do usuário em 19/08/2026: os dois juntos numa "
                    "exclusão só, em vez das duas linhas separadas da planilha antiga (2.1/2.5). Só conta "
                    "CFOPs que aparecem na Rotina 1024 desta competência dentro de 1.1/1.4 (mesma limitação "
                    "da Conferência 1024×1096 do Lucro Real).",
        },
    ))
    linhas.append(LinhaApuracaoPresumido("2.2", LINHAS_PENDENTES["2.2"], Decimal("0"), Decimal("0"), manual=True))

    icms_saida = _soma_icms_saida_nao_isento_escopado(CFOPS_1_1 | CFOPS_1_4)
    linhas.append(LinhaApuracaoPresumido(
        "2.3", "(-) ICMS Apuração - Destacado Saídas", Decimal("0"), Decimal("0"),
        detalhe={
            "base_total": str(icms_saida),
            "nota": "CORRIGIDO em 20/08/2026: soma de relatorio_pc_itens.valor_nao_tributado (Relatório "
                    "1096, saída) dos itens que NÃO são CST 6/7 — que já é, item a item, o ICMS destacado "
                    "de cada item tributado. Antes somava valor_icms da Rotina 1024 por CFOP inteiro, que "
                    "inclui o ICMS dos itens isentos e descontava esse ICMS duas vezes junto com a linha "
                    "\"2.1\" (prova numérica real: CFOP 5102/filial F7/jul-2026, base menor em R$ 17.285,44 "
                    "— o ICMS dos itens isentos daquele CFOP/mês). Ver metodologia do projeto.",
        },
    ))

    base_devolucao = _soma_bruta("entrada", CFOPS_1_2_DEVOLUCAO_VENDA) - _soma_icms("entrada", CFOPS_1_2_DEVOLUCAO_VENDA)
    linhas.append(LinhaApuracaoPresumido(
        "1.2", "(-) Devolução de Venda", Decimal("0"), Decimal("0"),
        detalhe={
            "base_total": str(base_devolucao),
            "nota": "Valor Contábil − ICMS destacado (Rotina 1024, entrada) dos CFOPs de devolução de venda "
                    "(1202/1411/2202/2411/3202) — único abatimento de receita permitido no regime "
                    "cumulativo (não é crédito, é a própria venda sendo desfeita). Código \"1.2\" mantido "
                    "igual à planilha antiga, mesmo aparecendo dentro da seção de Exclusões.",
        },
    ))
    linhas.append(LinhaApuracaoPresumido("2.6", LINHAS_PENDENTES["2.6"], Decimal("0"), Decimal("0"), manual=True))

    total_exclusoes = isentos_saida + icms_saida + base_devolucao
    linhas.append(LinhaApuracaoPresumido("2", "2 - Total das Exclusões", Decimal("0"), Decimal("0"),
                                          detalhe={"base_total": str(total_exclusoes)}))

    # --- 3 — Base de Cálculo ---
    base_calculo = total_receitas - total_exclusoes
    linhas.append(LinhaApuracaoPresumido(
        "3", "3 - Base de Cálculo (Receitas Tributáveis - Exclusões) = 1 - 2", Decimal("0"), Decimal("0"),
        detalhe={"base_total": str(base_calculo)},
    ))

    # --- 3.1 — Incidência residual sobre Produtos Isentos, LC 224/2025 (20/08/2026; fonte = tabela desde a
    # migração 009) -----------------------------------------------------------------------------------------
    # Base própria (Valor Contábil dos itens CST 6/7 cujo NCM está cadastrado em `ncms_lc224_pc`), à parte
    # da Base de Cálculo "3" — esses itens JÁ estão inteiros dentro da exclusão "2.1" (CST 6/7), então isto
    # não muda a base "3"/"1"/"2"; é uma incidência residual somada só no final (linhas "4.1"/"4.2"), mesmo
    # padrão de como a planilha antiga tratava essa linha (soma a mais só entre a Contribuição Apurada e o
    # Saldo Final). Alíquotas vêm por NCM da tabela (podem diferir NCM a NCM, embora hoje todos os
    # cadastrados usem a mesma: PIS 0,0650% / COFINS 0,30% — 1/10 da alíquota cheia do Presumido).
    base_lc224, pis_lc224_bruto, cofins_lc224_bruto, detalhe_lc224_ncm = _calcular_lc224_escopado(
        CFOPS_1_1 | CFOPS_1_4
    )
    pis_lc224 = _arred(pis_lc224_bruto) if base_lc224 > 0 else Decimal("0")
    cofins_lc224 = _arred(cofins_lc224_bruto) if base_lc224 > 0 else Decimal("0")
    linhas.append(LinhaApuracaoPresumido(
        "3.1", "(+) Apuração Produtos Isentos - Lei Complementar 224/2025 (NCMs específicos)",
        pis_lc224, cofins_lc224,
        detalhe={
            "base_total": str(base_lc224),
            "nota": "Base = Valor Contábil (Relatório 1096, saída) dos itens com CST 6/7 (já dentro da "
                    "exclusão '2.1') cujo NCM está cadastrado em ncms_lc224_pc (tabela editável no Supabase "
                    "desde 20/08/2026 — sql/009_ncms_lc224_pc.sql, substituiu a lista fixa que estava no "
                    "código). Só conta CFOPs ativos na Rotina 1024 desta competência dentro de 1.1/1.4 "
                    "(mesmo escopo das demais linhas 2.x/3.1).",
            "base_por_ncm": {k: str(v) for k, v in detalhe_lc224_ncm.items()},
        },
    ))

    # --- P/C — Contribuição apurada sobre a base (uma vez só, diferente do Lucro Real) ---
    pis_apurado = _arred(base_calculo * ALIQ_PIS) if base_calculo > 0 else Decimal("0")
    cofins_apurado = _arred(base_calculo * ALIQ_COFINS) if base_calculo > 0 else Decimal("0")
    linhas.append(LinhaApuracaoPresumido("P", "Art. 2º - Valor da Contribuição do PIS Alíquota 0,65%",
                                          pis_apurado, Decimal("0")))
    linhas.append(LinhaApuracaoPresumido("C", "Art. 2º - Valor da Contribuição da COFINS Alíquota 3,00%",
                                          Decimal("0"), cofins_apurado))

    # --- Resultado / DARF (sem saldo credor anterior nem crédito — regime cumulativo) ---
    # A partir de 20/08/2026, inclui a incidência residual da linha "3.1" (LC 224/2025) — soma "P"/"C" com
    # "3.1" (pis_lc224/cofins_lc224), do mesmo jeito que a planilha antiga somava essa linha só depois da
    # Contribuição Apurada, não dentro da Base de Cálculo "3".
    total_pis_devido = pis_apurado + pis_lc224
    total_cofins_devido = cofins_apurado + cofins_lc224
    linhas.append(LinhaApuracaoPresumido(
        "4.1", "Saldo Final Devedor ou (Credor) de PIS - cumulativo", total_pis_devido, Decimal("0"),
        detalhe={"nota": "= P (Art. 2º) + 3.1 (LC 224/2025)."} if pis_lc224 else {},
    ))
    linhas.append(LinhaApuracaoPresumido(
        "4.2", "Saldo Final Devedor ou (Credor) de COFINS - cumulativo", Decimal("0"), total_cofins_devido,
        detalhe={"nota": "= C (Art. 2º) + 3.1 (LC 224/2025)."} if cofins_lc224 else {},
    ))
    linhas.append(LinhaApuracaoPresumido("5.1", LINHAS_PENDENTES["5.1"], Decimal("0"), Decimal("0"), manual=True))
    linhas.append(LinhaApuracaoPresumido("5.2", LINHAS_PENDENTES["5.2"], Decimal("0"), Decimal("0"), manual=True))

    pagar_pis = total_pis_devido if total_pis_devido > 0 else Decimal("0")
    pagar_cofins = total_cofins_devido if total_cofins_devido > 0 else Decimal("0")
    linhas.append(LinhaApuracaoPresumido("6.1", "Líquido a pagar em DARF - TOTAL PIS - DARF 8109",
                                          pagar_pis, Decimal("0")))
    linhas.append(LinhaApuracaoPresumido("6.2", "Líquido a pagar em DARF - TOTAL COFINS - DARF 2172",
                                          Decimal("0"), pagar_cofins))
    linhas.append(LinhaApuracaoPresumido("7.3", "Líquido a pagar em DARF - TOTAL PIS E COFINS",
                                          pagar_pis, pagar_cofins))

    return linhas


def salvar_apuracao_pc_presumido(session, competencia_id: int, linhas: list[LinhaApuracaoPresumido]):
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
# CONFERÊNCIA 1024 × 1096 — só saída (regime cumulativo não usa entrada, exceto devolução de venda, que não
# entra nesta conferência por CFOP a CFOP — mesmo escopo do Lucro Real, "mostra TODO CFOP encontrado").
# ==================================================================================================
TOLERANCIA_CONFERENCIA = Decimal("1.00")

# Razão COFINS/PIS (3,00% ÷ 0,65%) — assinatura de uma divergência causada por ICMS descontado duas vezes
# nos itens isentos (ver docstring de `_linha_conferencia`, 20/08/2026). Tolerância relativa de 15%: cobre o
# ruído de arredondamento de somar milhares de itens (visto na prática: R$ 1,97 de ruído em R$ 2,1 milhões,
# bem dentro da faixa) sem deixar passar causas realmente diferentes (alíquota de item monofásico/ST, que
# tende a dar uma razão bem distante de 4,615).
RAZAO_COFINS_PIS = ALIQ_COFINS / ALIQ_PIS
TOLERANCIA_RELATIVA_RAZAO_ICMS_ISENTO = Decimal("0.15")


def conferencia_1024_x_1096_presumido(session, competencia_id: int) -> list[dict]:
    """CORRIGIDO em 20/08/2026 (ver `_somar_icms_saida_nao_isento_por_cfop`): o lado "1024" agora usa a
    MESMA fórmula corrigida da Apuração (`valor_contabil(1024) - icms_nao_isento(1096) - cst_isento(1096)`),
    não mais `valor_icms` agregado do 1024 — senão a Conferência ficaria mostrando uma conta diferente da
    que a Apuração realmente faz. `icms_1024` (valor_icms agregado, cru, direto da Rotina 1024) continua
    calculado só como contexto/auditoria (mostra o ICMS total que o RAICMS relatou pro CFOP), mas não entra
    mais na fórmula. `1096` = soma direta de valor_pis/valor_cofins dos itens (sempre foi a fonte correta)."""
    linhas_1024 = session.execute(text("""
        select cfop, sum(valor_contabil) as valor_contabil, sum(valor_icms) as valor_icms
        from resumo_1024_pc where competencia_id = :cid and tipo_operacao = 'saida'
        group by cfop
    """), {"cid": competencia_id}).mappings().all()

    cst_isento_por_cfop = _somar_cst_isento_por_cfop(session, competencia_id)
    icms_nao_isento_por_cfop = _somar_icms_saida_nao_isento_por_cfop(session, competencia_id)

    linhas_1096 = session.execute(text("""
        select cfop, sum(valor_pis) as valor_pis, sum(valor_cofins) as valor_cofins
        from relatorio_pc_itens where competencia_id = :cid and tipo_operacao = 'saida'
        group by cfop
    """), {"cid": competencia_id}).mappings().all()
    por_cfop_1096 = {r["cfop"]: r for r in linhas_1096}

    vistos = set()
    resultado = []
    for r in linhas_1024:
        vistos.add(r["cfop"])
        icms_1024_agregado = _dec(r["valor_icms"])  # cru, só contexto — ver docstring
        icms_correto = icms_nao_isento_por_cfop.get(r["cfop"], Decimal("0"))
        isento = cst_isento_por_cfop.get(r["cfop"], Decimal("0"))
        base = _dec(r["valor_contabil"]) - icms_correto - isento
        pis_1024 = _arred(base * ALIQ_PIS) if base > 0 else Decimal("0")
        cofins_1024 = _arred(base * ALIQ_COFINS) if base > 0 else Decimal("0")
        r1096 = por_cfop_1096.get(r["cfop"])
        pis_1096 = _dec(r1096["valor_pis"]) if r1096 else None
        cofins_1096 = _dec(r1096["valor_cofins"]) if r1096 else None
        resultado.append(_linha_conferencia(r["cfop"], pis_1024, cofins_1024, pis_1096, cofins_1096,
                                              icms_1024_agregado))

    for cfop, r1096 in por_cfop_1096.items():
        if cfop in vistos:
            continue
        resultado.append(_linha_conferencia(cfop, None, None, _dec(r1096["valor_pis"]), _dec(r1096["valor_cofins"]),
                                              None))

    resultado.sort(key=lambda r: r["cfop"])
    return resultado


def _linha_conferencia(cfop, pis_1024, cofins_1024, pis_1096, cofins_1096, icms_1024):
    """CORRIGIDO em 20/08/2026 depois de reconciliar com o "Relatório de conferência PIS/COFINS e ICMS" (um
    3º relatório do Winthor, item a item, que o usuário trouxe pra bater a conta manualmente). A explicação
    anterior aqui estava ERRADA: não é "1024 exclui ICMS, 1096 não" — os dois relatórios oficiais do Winthor
    (1096 "combinação CFOP/CST/NCM" e o "conferência PIS/COFINS e ICMS") já excluem ICMS item a item e batem
    entre si ao centavo. A causa real, confirmada com dados reais (CFOP 5102, filial F7, jul/2026, conferido
    item a item nos 26.399 itens do relatório novo): a fórmula do 1024 (`valor_contabil − valor_icms −
    isento`) desconta o ICMS uma vez AGREGADO por CFOP (`valor_icms` da Rotina 1024, que inclui o ICMS de
    TODOS os itens, inclusive os isentos de PIS/COFINS) e desconta o valor contábil dos itens CST 6/7 outra
    vez — ou seja, o ICMS que pertence aos itens isentos é descontado DUAS vezes. O tamanho do erro é
    exatamente o ICMS destacado só dos itens isentos (no exemplo real: R$ 17.285,44 num CFOP de R$ 2,6
    milhões) — não o `icms_1024` inteiro do CFOP (esse é ~25x maior e não serve de referência sozinho, foi o
    erro da versão anterior desta função).

    A Rotina 1024 não separa ICMS por CST de PIS/COFINS, e o Relatório 1096 hoje importado não guarda ICMS
    por item — então não dá pra calcular o valor exato do "ICMS dos isentos" só com os dados já importados
    (precisaria importar aquele 3º relatório). Em vez disso, usamos a ASSINATURA da causa: quando a razão
    diff_cofins ÷ diff_pis bate com ALIQ_COFINS ÷ ALIQ_PIS (3% ÷ 0,65% = 4,615), é porque a diferença toda
    vem de um único valor em R$ sendo aplicado nas duas alíquotas — a assinatura exata de "ICMS descontado
    duas vezes" (confirmado matematicamente: se diff_pis = -X × ALIQ_PIS e diff_cofins = -X × ALIQ_COFINS
    para o MESMO X, a razão dá exatamente ALIQ_COFINS/ALIQ_PIS, não importa o valor de X). Quando a razão não
    bate, a causa é outra (item com alíquota diferente da cheia, CFOP sem item numa das fontes, etc.)."""
    diff_pis = (pis_1024 - pis_1096) if (pis_1024 is not None and pis_1096 is not None) else None
    diff_cofins = (cofins_1024 - cofins_1096) if (cofins_1024 is not None and cofins_1096 is not None) else None
    if pis_1024 is None or pis_1096 is None:
        situacao = "Só em uma fonte"
    elif abs(diff_pis) > TOLERANCIA_CONFERENCIA or abs(diff_cofins) > TOLERANCIA_CONFERENCIA:
        situacao = "Divergente"
    else:
        situacao = "OK"

    causa_provavel = None
    icms_isento_implicito = None
    if situacao == "Divergente":
        # Só testa a razão quando os dois diffs são negativos e o diff_pis não é ínfimo (perto de zero a
        # razão fica instável/sem sentido — nesses casos cai em "Outra causa", conferir manualmente).
        if diff_pis < 0 and diff_cofins < 0 and abs(diff_pis) >= Decimal("0.10"):
            razao = diff_cofins / diff_pis
            desvio_relativo = abs(razao - RAZAO_COFINS_PIS) / RAZAO_COFINS_PIS
            if desvio_relativo <= TOLERANCIA_RELATIVA_RAZAO_ICMS_ISENTO:
                causa_provavel = ("ICMS destacado nos itens isentos (CST 6/7) descontado 2x pela fórmula do "
                                  "1024 — não é erro de importação")
                # Estima o ICMS dos itens isentos a partir do próprio diff (não é medido direto — a Rotina
                # 1024 não separa ICMS por CST de PIS/COFINS). Usa a média das duas implicações (PIS e
                # COFINS) pra reduzir o ruído de arredondamento de cada uma isoladamente.
                estimativa_via_pis = -diff_pis / ALIQ_PIS
                estimativa_via_cofins = -diff_cofins / ALIQ_COFINS
                icms_isento_implicito = _arred((estimativa_via_pis + estimativa_via_cofins) / 2)
        if causa_provavel is None:
            causa_provavel = "Outra causa (ver CST/alíquota no detalhamento abaixo)"
    elif situacao == "Só em uma fonte":
        causa_provavel = "CFOP sem item importado numa das duas fontes"

    return {
        "cfop": cfop, "tipo_operacao": "saida",
        "pis_1024": pis_1024, "cofins_1024": cofins_1024,
        "pis_1096": pis_1096, "cofins_1096": cofins_1096,
        "diff_pis": diff_pis, "diff_cofins": diff_cofins,
        "icms_1024": icms_1024, "icms_isento_implicito": icms_isento_implicito,
        "situacao": situacao, "causa_provavel": causa_provavel,
    }


def detalhar_cfop_presumido(session, competencia_id: int, cfop: int) -> dict:
    """Drill-down de UM CFOP (pedido do usuário em 19/08/2026, depois de ver a Conferência com vários
    CFOPs "Divergente" sem conseguir identificar a causa): devolve (a) o que a Rotina 1024 trouxe por filial
    para este CFOP (valor_contabil/valor_icms — o insumo bruto do lado "1024" da conferência) e (b) os itens
    do Relatório 1096 deste CFOP agrupados por CST (quantidade, soma de valor_contabil/valor_pis/
    valor_cofins, e as alíquotas de PIS/COFINS efetivamente usadas por item — min/max, pra pular à vista
    quando um item tem uma alíquota diferente da cheia 0,65%/3%, ex.: monofásica/ST, o que sozinho já explica
    a maior parte das divergências: a Rotina 1024 soma o CFOP inteiro e aplica uma alíquota só, mas o
    Relatório 1096 respeita a alíquota de cada item individualmente)."""
    linhas_1024 = session.execute(text("""
        select e.filial_winthor, e.razao_social, r.valor_contabil, r.valor_icms
        from resumo_1024_pc r join empresas e on e.id = r.empresa_id
        where r.competencia_id = :cid and r.tipo_operacao = 'saida' and r.cfop = :cfop
        order by e.filial_winthor nulls last, e.razao_social
    """), {"cid": competencia_id, "cfop": cfop}).mappings().all()

    por_cst = session.execute(text("""
        select ri.cst, c.descricao as cst_descricao, count(*) as n_itens,
               sum(ri.valor_contabil) as valor_contabil, sum(ri.valor_pis) as valor_pis,
               sum(ri.valor_cofins) as valor_cofins, min(ri.aliq_pis) as aliq_pis_min,
               max(ri.aliq_pis) as aliq_pis_max, min(ri.aliq_cofins) as aliq_cofins_min,
               max(ri.aliq_cofins) as aliq_cofins_max
        from relatorio_pc_itens ri
        left join cst_pis_cofins c on c.codigo = ri.cst
        where ri.competencia_id = :cid and ri.tipo_operacao = 'saida' and ri.cfop = :cfop
        group by ri.cst, c.descricao
        order by ri.cst
    """), {"cid": competencia_id, "cfop": cfop}).mappings().all()

    return {
        "1024_por_filial": [dict(r) for r in linhas_1024],
        "1096_por_cst": [dict(r) for r in por_cst],
    }
