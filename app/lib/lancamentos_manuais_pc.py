"""
Lançamentos manuais de crédito de PIS/COFINS — Aluguéis (Prédios / Máquinas e Equipamentos) e Depreciação.
Único tipo de lançamento manual implementado nesta versão (pedido do usuário em 14/08/2026: "só Aluguéis e
Depreciação por enquanto") — as demais linhas manuais da apuração (energia elétrica, fretes Supply Log,
receitas financeiras etc.) ficam pendentes, ver metodologia no projeto "PIS/COFINS".

O crédito é sempre calculado automaticamente a partir da base informada pelo analista: valor_pis = base ×
1,65%, valor_cofins = base × 7,60% (alíquotas cheias do regime não-cumulativo) — o analista não digita o
PIS/COFINS diretamente, só a base (valor do aluguel/depreciação do mês), para não haver erro de conta.
"""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

ALIQ_PIS = Decimal("0.0165")
ALIQ_COFINS = Decimal("0.0760")

TIPOS = {
    "aluguel_predio_credito": "Aluguéis pagos a PJ (Prédios)",
    "aluguel_maquinas_credito": "Aluguéis pagos a PJ (Máquinas e Equipamentos)",
    "depreciacao_credito": "Depreciações Máquinas e Equip. e Outros Bens do Ativo Imobilizado",
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


def adicionar(session, competencia_id, tipo, descricao, base_valor, usuario=None):
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de lançamento inválido: {tipo}")
    base = Decimal(str(base_valor))
    valor_pis = _arred(base * ALIQ_PIS)
    valor_cofins = _arred(base * ALIQ_COFINS)
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
