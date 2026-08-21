"""
Receitas Financeiras (linha 3 da apuração, alíquota reduzida — Lei 8.426/2015: PIS 0,65% / COFINS 4%, bem
menor que a alíquota cheia do regime não-cumulativo, 1,65%/7,60%). Pedido do usuário em 19/08/2026, mostrando
o print da aba "3- RECEITAS FINANCEIRAS" da planilha antiga: replicar os 6 subitens (3.1 a 3.6) como campos
editáveis na tela, cuja soma vira a base da linha 3 — em vez de um campo único de base (like Aluguéis/
Depreciação), porque o usuário confirmou explicitamente "subitens como no print".

Por que não reaproveitar `lancamentos_manuais_pc.py`: lá as alíquotas são sempre as cheias de CRÉDITO
(1,65%/7,60%, reduz o que se paga) — aqui é alíquota REDUZIDA e é DÉBITO (aumenta o que se paga). Mesmo
"formato de lançamento manual", regra de cálculo e sinal totalmente diferentes; misturar os dois no mesmo
módulo teria exigido um parâmetro de alíquota/sinal por tipo, mais confuso do que dois módulos pequenos e
diretos.

Modelagem: diferente de lancamentos_manuais_pc (lista de lançamentos avulsos, pode ter vários por tipo por
competência), aqui é UM valor por (competência, subitem) — `receitas_financeiras_pc`, `unique(competencia_id,
tipo)`, upsert — porque cada subitem do print é um total mensal único (ex.: "Juros recebidos" do mês),
não uma lista de lançamentos individuais. Mesmo padrão de `saldo_credor_anterior_pc`.
"""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

# Alíquotas reduzidas da Lei 8.426/2015 — bem diferentes das cheias (1,65%/7,60%) usadas no resto da
# apuração e em lancamentos_manuais_pc. Mantidas aqui, não em calculo_pis_cofins_lucro_real.py, para ficarem
# junto da única linha que as usa (linha 3) — mas calcular_apuracao_pc importa e usa estas constantes na
# hora de montar a linha "3", não duplica o valor.
ALIQ_PIS_FINANCEIRAS = Decimal("0.0065")
ALIQ_COFINS_FINANCEIRAS = Decimal("0.04")

# Ordem = mesma do print da planilha antiga (3.1 a 3.6) — usada tanto para render na tela quanto para somar
# a base na apuração (ver calculo_pis_cofins_lucro_real.calcular_apuracao_pc).
TIPOS_RECEITA_FINANCEIRA = {
    "desconto_obtido": "3.1 — Receita de Desconto Obtido",
    "variacao_monetaria": "3.2 — Variação Monetária",
    "rendimento_aplicacao": "3.3 — Rendimento de Aplicação",
    "juros_recebidos": "3.4 — Juros recebidos",
    "multas_recebidas": "3.5 — Multas recebidas",
    "outras_receitas": "3.6 — Outras Receitas",
}


def _arred(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def carregar_receitas_financeiras(session, competencia_id) -> dict:
    """Devolve {tipo: Decimal(valor)} para todos os 6 subitens desta competência — subitens ainda não
    salvos (nunca editados) entram com Decimal('0'), para a tela sempre ter os 6 campos preenchidos."""
    rows = session.execute(text("""
        select tipo, valor from receitas_financeiras_pc where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()
    valores = {t: Decimal("0") for t in TIPOS_RECEITA_FINANCEIRA}
    for r in rows:
        if r["tipo"] in valores:
            valores[r["tipo"]] = Decimal(str(r["valor"]))
    return valores


def salvar_receitas_financeiras(session, competencia_id, valores: dict, usuario=None):
    """`valores` = {tipo: novo_valor} — grava só os tipos presentes no dict (upsert por tipo). Devolve a
    base total (soma dos 6, depois de salvar) para a tela mostrar o preview de PIS/COFINS sem precisar de
    uma segunda consulta."""
    usuario = usuario or {}
    for tipo, valor in valores.items():
        if tipo not in TIPOS_RECEITA_FINANCEIRA:
            raise ValueError(f"Subitem de Receita Financeira inválido: {tipo}")
        session.execute(text("""
            insert into receitas_financeiras_pc (competencia_id, tipo, valor, atualizado_por, atualizado_por_email)
            values (:cid, :tipo, :valor, :uid, :uemail)
            on conflict (competencia_id, tipo) do update
                set valor = excluded.valor, atualizado_por = excluded.atualizado_por,
                    atualizado_por_email = excluded.atualizado_por_email, updated_at = now()
        """), {
            "cid": competencia_id, "tipo": tipo, "valor": str(Decimal(str(valor))),
            "uid": usuario.get("id"), "uemail": usuario.get("email"),
        })
    session.commit()
    return sum((Decimal(str(v)) for v in valores.values()), Decimal("0"))


def calcular_pis_cofins(base: Decimal) -> tuple:
    """PIS/COFINS pela alíquota reduzida da Lei 8.426/2015 — usada tanto pelo preview na tela quanto por
    calcular_apuracao_pc, pra não haver duas fórmulas divergentes."""
    return _arred(base * ALIQ_PIS_FINANCEIRAS), _arred(base * ALIQ_COFINS_FINANCEIRAS)
