"""
Lançamentos manuais de PIS/COFINS que não vêm de CFOP da Rotina 1024/Relatório 1096 — Aluguéis (Prédios /
Máquinas e Equipamentos) e Depreciação, implementados em 14/08/2026 ("só Aluguéis e Depreciação por
enquanto").

Estendido em 20/08/2026 (sessão de continuação — pedido do usuário: "criar lançamento manual para todas"
as linhas que ficavam com ⏳ pendente sem nenhum campo pra preencher) pra cobrir o resto das linhas
manuais/fora do escopo do 1024/1096 documentadas em "Pontos em aberto" nas duas metodologias:

- **Lucro Real** (`TIPOS`, alíquota cheia do regime não-cumulativo — 1,65%/7,60% pros dois lados, débito e
  crédito): 1.3 (Serviços) e 1.5 (Aluguel recebido) somam em `debito_pis_total`/`debito_cofins_total`
  (linha "1"); 5.9 (Fretes Supply Log) soma em `credito_pis_total`/`credito_cofins_total` (linha "5"), MESMO
  padrão de Aluguéis/Depreciação já existente; 2.4/2.6 (débito) e 6.3/6.6 (crédito) são EXCLUSÕES — o valor
  de PIS/COFINS calculado pra elas é SUBTRAÍDO do total do lado correspondente, não somado (ver
  `calculo_pis_cofins_lucro_real.calcular_apuracao_pc`, blocos "lançamentos manuais — exclusões").
- **Lucro Presumido** (`TIPOS_PRESUMIDO`, alíquota cheia do regime cumulativo — 0,65%/3,00%): diferente do
  Real, o Presumido calcula PIS/COFINS uma vez só em cima da Base de Cálculo final ("3" = "1" − "2") — os
  lançamentos manuais aqui só contribuem com BASE (`base_valor`), somada em `total_receitas` (1.3/1.5/1.6)
  ou `total_exclusoes` (2.2/2.6) ANTES de "3" ser calculada; `valor_pis`/`valor_cofins` gravados no
  lançamento (via `aliq_pis`/`aliq_cofins` do Presumido) ficam só de referência/auditoria — não são somados
  diretamente em lugar nenhum do cálculo (ver `calculo_pis_cofins_lucro_presumido.calcular_apuracao_pc_
  presumido`).

O valor de PIS/COFINS de cada lançamento é sempre calculado automaticamente a partir da base informada pelo
analista (`valor_pis = base × aliq_pis`, `valor_cofins = base × aliq_cofins`) — o analista nunca digita
PIS/COFINS diretamente, só a base em R$, para não haver erro de conta. `aliq_pis`/`aliq_cofins` são
parâmetros de `adicionar()` desde 20/08/2026 (antes eram só as constantes do módulo, fixas na alíquota do
Real) — quem chama do Lucro Real pode omitir (usa `ALIQ_PIS`/`ALIQ_COFINS` por padrão, mesmo valor de
sempre); quem chama do Presumido passa `ALIQ_PIS_PRESUMIDO`/`ALIQ_COFINS_PRESUMIDO` explicitamente.
"""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

ALIQ_PIS = Decimal("0.0165")
ALIQ_COFINS = Decimal("0.0760")

ALIQ_PIS_PRESUMIDO = Decimal("0.0065")
ALIQ_COFINS_PRESUMIDO = Decimal("0.0300")

TIPOS = {
    "aluguel_predio_credito": "Aluguéis pagos a PJ (Prédios)",
    "aluguel_maquinas_credito": "Aluguéis pagos a PJ (Máquinas e Equipamentos)",
    "depreciacao_credito": "Depreciações Máquinas e Equip. e Outros Bens do Ativo Imobilizado",
    # Novos em 20/08/2026 — ver docstring do módulo. Nomes de linha entre parênteses = numeração da apuração
    # (LAYOUT_LINHAS em calculo_pis_cofins_lucro_real.py).
    "servicos_debito": "(1.3) Faturamento Bruto (Prestação de Serviços)",
    "aluguel_recebido_debito": "(1.5) Receitas de Aluguel de Bens",
    "fretes_supply_log_credito": "(5.9) Fretes SUPPLY LOG",
    "icms_substituicao_exclusao": "(2.4) (-) ICMS Substituição",
    "exportacao_debito_exclusao": "(2.6) (-) Exportação de Mercadorias para o Exterior (Débito)",
    "ipi_exclusao": "(6.3) (-) IPI",
    "exportacao_credito_exclusao": "(6.6) (-) Exportação de Mercadorias para o Exterior (Crédito)",
}

# Lucro Presumido — separado de TIPOS (chaves próprias, sufixo "_presumido") pra não colidir com os tipos do
# Real na mesma tabela `lancamentos_manuais_pc`; `competencia_id` já escopa pro regime certo (via
# `competencias.modulo`), o sufixo é só clareza extra pra quem olhar a tabela direto no banco.
TIPOS_PRESUMIDO = {
    "servicos_debito_presumido": "(1.3) Faturamento Bruto (Prestação de Serviços)",
    "aluguel_recebido_debito_presumido": "(1.5) Receitas de Aluguel de Bens",
    "demais_receitas_debito_presumido": "(1.6) Demais Receitas Operacionais",
    "monofasica_exclusao_presumido": "(2.2) (-) Incidência da Contribuição Monofásica",
    "exportacao_exclusao_presumido": "(2.6) (-) Exportação de Mercadorias para o Exterior",
}


def _arred(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def listar(session, competencia_id):
    rows = session.execute(text("""
        select id, tipo, descricao, base_valor, valor_pis, valor_cofins, created_at
        from lancamentos_manuais_pc
        where competencia_id = :cid
        order by created_at desc
    """), {"cid": competencia_id}).mappings().all()
    return [dict(r) for r in rows]


def adicionar(session, competencia_id, tipo, descricao, base_valor, usuario=None, aliq_pis=None,
              aliq_cofins=None):
    """`aliq_pis`/`aliq_cofins` (novos em 20/08/2026) — quem chama do Lucro Presumido passa
    `ALIQ_PIS_PRESUMIDO`/`ALIQ_COFINS_PRESUMIDO`; omitindo os dois, usa `ALIQ_PIS`/`ALIQ_COFINS` (Real,
    comportamento de sempre, retrocompatível com as chamadas existentes de Aluguéis/Depreciação)."""
    if tipo not in TIPOS and tipo not in TIPOS_PRESUMIDO:
        raise ValueError(f"Tipo de lançamento inválido: {tipo}")
    aliq_pis = aliq_pis if aliq_pis is not None else ALIQ_PIS
    aliq_cofins = aliq_cofins if aliq_cofins is not None else ALIQ_COFINS
    base = Decimal(str(base_valor))
    valor_pis = _arred(base * aliq_pis)
    valor_cofins = _arred(base * aliq_cofins)
    usuario = usuario or {}
    session.execute(text("""
        insert into lancamentos_manuais_pc
            (competencia_id, tipo, descricao, base_valor, valor_pis, valor_cofins, criado_por)
        values (:cid, :tipo, :descricao, :base, :vpis, :vcofins, :criado_por)
    """), {
        "cid": competencia_id, "tipo": tipo, "descricao": descricao, "base": str(base),
        "vpis": str(valor_pis), "vcofins": str(valor_cofins), "criado_por": usuario.get("id"),
    })
    session.commit()
    return {"valor_pis": valor_pis, "valor_cofins": valor_cofins}


def excluir(session, lancamento_id):
    session.execute(text("delete from lancamentos_manuais_pc where id = :id"), {"id": lancamento_id})
    session.commit()


def excluir_removidos(session, df_original, df_editado) -> int:
    """Mesmo padrão do módulo ICMS (`lib/lancamentos_manuais.py`): compara antes/depois de uma grade
    editável e exclui do banco os lançamentos cujo `id` sumiu — linhas novas (sem id) são ignoradas, a
    inclusão continua só pelo formulário dedicado."""
    if df_original.empty:
        return 0
    ids_originais = set(df_original["id"].dropna().astype(int))
    ids_editados = set(df_editado["id"].dropna().astype(int)) if "id" in df_editado.columns and not df_editado.empty else set()
    removidos = ids_originais - ids_editados
    for lid in removidos:
        session.execute(text("delete from lancamentos_manuais_pc where id = :id"), {"id": int(lid)})
    if removidos:
        session.commit()
    return len(removidos)


def salvar_saldo_anterior(session, competencia_id, saldo_pis, saldo_cofins):
    session.execute(text("""
        insert into saldo_credor_anterior_pc (competencia_id, saldo_pis, saldo_cofins, updated_at)
        values (:cid, :pis, :cofins, now())
        on conflict (competencia_id) do update
            set saldo_pis = excluded.saldo_pis, saldo_cofins = excluded.saldo_cofins, updated_at = now()
    """), {"cid": competencia_id, "pis": str(saldo_pis), "cofins": str(saldo_cofins)})
    session.commit()


def carregar_saldo_anterior(session, competencia_id):
    row = session.execute(text("""
        select saldo_pis, saldo_cofins from saldo_credor_anterior_pc where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().first()
    if not row:
        return {"saldo_pis": Decimal("0"), "saldo_cofins": Decimal("0")}
    return {"saldo_pis": Decimal(str(row["saldo_pis"])), "saldo_cofins": Decimal(str(row["saldo_cofins"]))}
