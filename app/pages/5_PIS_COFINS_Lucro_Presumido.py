"""
PIS/COFINS — Lucro Presumido (regime cumulativo). Construída em 19/08/2026, primeira versão — reaproveita a
MESMA infraestrutura de importação do Lucro Real (ver `1_Importar_Relatorios.py`, seletor de "Módulo") e as
mesmas tabelas (`resumo_1024_pc`, `relatorio_pc_itens`, `apuracao_pc_linhas`), já que `competencias.modulo`
distingue os dois desde o schema inicial (14/08/2026). O motor de cálculo está em
`lib/calculo_pis_cofins_lucro_presumido.py` — leia a docstring de lá antes de mexer aqui (ela documenta as
diferenças de metodologia em relação ao Lucro Real e os pontos em aberto).

Escopo desta primeira versão: só Apuração + Conferência 1024×1096. Sem "Ajustes Manuais"/"Regras de CST"/
grade editável do Relatório 1096 (o Lucro Real também começou assim em 14/08/2026 e ganhou essas telas aos
poucos, conforme pedido) — extensível depois, seguindo o mesmo padrão de arquivos.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decimal import Decimal

import streamlit as st
from sqlalchemy import text

from lib.auth import require_login, logout_button
from lib.db import get_session
from lib.formatacao import formatar_moeda
from lib.status_apuracao_pc import status_competencia
from lib import importacao_pc
from lib.calculo_pis_cofins_lucro_presumido import (
    calcular_apuracao_pc_presumido, salvar_apuracao_pc_presumido, ordenar_linhas_para_exibicao,
    LAYOUT_LINHAS, conferencia_1024_x_1096_presumido, detalhar_cfop_presumido,
)

MODULO = "pis_cofins_lucro_presumido"
REGIME_LIKE = "Lucro Presumido%"

st.set_page_config(page_title="PIS/COFINS Lucro Presumido", layout="wide")
require_login()
logout_button()
st.title("PIS/COFINS — Lucro Presumido")
st.caption(
    "Regime cumulativo (Lei 9.718/1998) — PIS 0,65% / COFINS 3,00% sobre a Base de Cálculo, sem crédito de "
    "entrada. Base = Rotina 1024 (só Saída) − Devolução de Venda − ICMS destacado − CST 6/7 (isentos). "
    "Desde 20/08/2026, a linha \"3.1\" soma uma incidência residual (PIS 0,0650% / COFINS 0,30% — Lei "
    "Complementar 224/2025) sobre os itens CST 6/7 de 10 NCMs específicos, mesmo esses itens já estando "
    "dentro da exclusão \"2.1\". Use **Importar Relatórios** (módulo \"Lucro Presumido\") para subir a "
    "Rotina 1024 e o Relatório 1096 antes de calcular aqui."
)

session = get_session()
grupos = importacao_pc.listar_grupos(session, regime_like=REGIME_LIKE)
if not grupos:
    st.warning("Nenhuma empresa em regime Lucro Presumido cadastrada ainda.")
    st.stop()

col1, col2, col3 = st.columns(3)
grupo = col1.selectbox(
    "Grupo (CNPJ raiz)", grupos,
    format_func=lambda g: f"{g['nome_grupo']} — {g['n_filiais']} filial(is)",
)
ano = col2.number_input("Ano", min_value=2020, max_value=2100, value=2026, step=1)
mes = col3.number_input("Mês", min_value=1, max_value=12, value=7, step=1)

competencia_id = importacao_pc.buscar_competencia_grupo(session, grupo["cnpj_raiz"], ano, mes, modulo=MODULO)
if not competencia_id:
    st.info("Nenhum dado importado para este grupo/período ainda. Use **Importar Relatórios** (módulo "
            "\"Lucro Presumido\").")
    st.stop()

comp_row = session.execute(
    text("select status from competencias where id = :id"), {"id": competencia_id}
).mappings().first()
status = status_competencia(session, competencia_id, comp_row["status"])
getattr(st, status["nivel"])(status["texto"])

aba_apuracao, aba_conferencia = st.tabs(["📋 Apuração", "📎 Conferência 1024×1096"])

# ---------------------------------------------------------------------------------------------- Apuração
with aba_apuracao:
    if st.button("🔄 Calcular apuração", type="primary"):
        linhas = calcular_apuracao_pc_presumido(session, competencia_id)
        salvar_apuracao_pc_presumido(session, competencia_id, linhas)
        st.success("Apuração calculada.")
        st.rerun()

    linhas_salvas = session.execute(text("""
        select linha, descricao, valor_pis, valor_cofins, manual, detalhe
        from apuracao_pc_linhas where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    if not linhas_salvas:
        st.info("Ainda não calculada — clique em 'Calcular apuração'.")
    else:
        def _base_da_linha(detalhe):
            if not detalhe or "base_total" not in detalhe:
                return None
            try:
                return Decimal(str(detalhe["base_total"]))
            except Exception:
                return None

        linhas_ordenadas = ordenar_linhas_para_exibicao(linhas_salvas)
        totais = {r["linha"]: r for r in linhas_salvas}

        cab = st.columns([5, 2, 2, 1.3])
        cab[0].markdown("**Linha**")
        cab[1].markdown("**Base**")
        cab[2].markdown("**PIS / COFINS**")
        cab[3].markdown("**Situação**")

        secao_atual = None
        for r in linhas_ordenadas:
            secao, _ordem, nivel = LAYOUT_LINHAS.get(r["linha"], ("Outras linhas", 999, 1))
            if secao != secao_atual:
                st.markdown(f"##### {secao}")
                secao_atual = secao
            destaque = nivel == 0
            indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if not destaque else ""
            abre, fecha = ("**", "**") if destaque else ("", "")
            base = _base_da_linha(r["detalhe"])
            base_txt = formatar_moeda(base) if base is not None else "—"
            pis_cofins_txt = "—"
            if r["valor_pis"] or r["valor_cofins"]:
                pis_cofins_txt = f"PIS {formatar_moeda(r['valor_pis'])} / COFINS {formatar_moeda(r['valor_cofins'])}"
            linha_cols = st.columns([5, 2, 2, 1.3])
            linha_cols[0].markdown(f"{indent}{abre}{r['linha']} — {r['descricao']}{fecha}",
                                    unsafe_allow_html=True)
            linha_cols[1].markdown(f"{abre}{base_txt}{fecha}")
            linha_cols[2].markdown(f"{abre}{pis_cofins_txt}{fecha}")
            linha_cols[3].markdown("⏳ pendente" if r["manual"] else "✅")

        st.markdown("---")
        if "7.3" in totais:
            pagar_pis = totais["7.3"]["valor_pis"]
            pagar_cofins = totais["7.3"]["valor_cofins"]
            st.markdown(f"""
<div style="border-left: 6px solid #16a34a; background: rgba(148,163,184,0.08); border-radius: 10px;
            padding: 18px 24px; margin: 6px 0 22px 0; text-align:center;">
  <span style="font-size:0.85rem; opacity:0.7; text-transform:uppercase; letter-spacing:.04em;">
    Resultado da Apuração — Líquido a pagar em DARF</span><br>
  <span style="font-size:2rem; font-weight:800; color:#16a34a;">
    {formatar_moeda(pagar_pis + pagar_cofins)}</span><br>
  <span style="font-size:0.85rem; opacity:0.7;">
    PIS (DARF 8109): {formatar_moeda(pagar_pis)} • COFINS (DARF 2172): {formatar_moeda(pagar_cofins)}</span>
</div>
""", unsafe_allow_html=True)

        n_pendentes_manual = sum(1 for r in linhas_salvas if r["manual"])
        if n_pendentes_manual:
            st.warning(
                f"{n_pendentes_manual} linha(s) desta apuração ainda são manuais/pendentes (valor zerado) — "
                f"ex.: Prestação de Serviços, Aluguel de Bens, Demais Receitas, Contribuição Monofásica, "
                f"Exportação, PERD/COMP. Se algum desses valores existir neste período, considere isso ao "
                f"ler o resultado final."
            )

# ---------------------------------------------------------------------------------------------- Conferência
with aba_conferencia:
    st.caption(
        "Comparação por CFOP (só Saída) entre o resultado da Rotina 1024 (usado na apuração) e a soma direta "
        "de valor_pis/valor_cofins do Relatório 1096 — só leitura, não muda nenhum valor calculado. "
        "Diferenças acima de R$ 1,00 aparecem como 'Divergente'. **Correção de 20/08/2026, confirmada com o "
        "usuário conferindo item a item contra um 3º relatório do Winthor ('Relatório de conferência PIS/"
        "COFINS e ICMS'): o Relatório 1096 já está correto — ele exclui o ICMS destacado item a item "
        "certinho. A causa real de divergência é a fórmula da Rotina 1024 (`Vl.Contábil − Vl.ICMS do CFOP "
        "inteiro − Vl.Contábil dos itens CST 6/7`) descontar duas vezes o ICMS que pertence aos itens "
        "isentos (uma vez embutido no ICMS agregado do CFOP, outra vez porque o valor contábil inteiro "
        "desses itens já foi zerado à parte).** Causa provável \"ICMS destacado nos itens isentos\" = a "
        "razão diff_cofins ÷ diff_pis bate com 3% ÷ 0,65% (4,615) — a assinatura matemática desse duplo "
        "desconto; 'icms_isento_implicito' é o valor em R$ que esse duplo desconto está tirando da base, "
        "estimado a partir do próprio diff (a Rotina 1024 não separa ICMS por CST de PIS/COFINS, então não "
        "dá pra medir esse valor direto sem importar aquele 3º relatório). Só vale abrir o 'Detalhar um "
        "CFOP' abaixo pras linhas com causa 'Outra causa'."
    )
    linhas_conf = conferencia_1024_x_1096_presumido(session, competencia_id)
    if not linhas_conf:
        st.info("Nenhum dado de Rotina 1024 nem de Relatório 1096 (saída) importado ainda para este grupo/período.")
    else:
        import pandas as pd

        fc1, fc2 = st.columns([1.7, 1.5])
        situacoes_disponiveis = sorted({l["situacao"] for l in linhas_conf})
        f_situacao = fc1.multiselect("Situação", situacoes_disponiveis, default=situacoes_disponiveis,
                                      key="conf_pres_f_situacao")
        f_cfop = fc2.text_input("Filtrar por CFOP", key="conf_pres_f_cfop")

        linhas_filtradas = [
            l for l in linhas_conf
            if l["situacao"] in f_situacao and (not f_cfop.strip() or str(l["cfop"]).startswith(f_cfop.strip()))
        ]

        n_div = sum(1 for l in linhas_conf if l["situacao"] not in ("OK",))
        if n_div:
            st.warning(f"{n_div} CFOP(s) com divergência ou presentes em só uma das fontes (no total, sem "
                       f"considerar o filtro acima).")
        else:
            st.success("Todos os CFOPs batem entre Rotina 1024 e Relatório 1096 (dentro da tolerância).")

        if not linhas_filtradas:
            st.info("Nenhum CFOP corresponde aos filtros selecionados.")
        else:
            st.caption(f"Mostrando {len(linhas_filtradas)} de {len(linhas_conf)} CFOP(s).")
            df_conf = pd.DataFrame(linhas_filtradas)
            # "Causa provável" (corrigido em 20/08/2026 — ver docstring de `_linha_conferencia`): pra CFOPs
            # "Divergente", testa se a razão diff_cofins/diff_pis bate com 3%/0,65% (assinatura de ICMS
            # descontado 2x nos itens isentos pela fórmula do 1024). "icms_1024" é o ICMS agregado do CFOP
            # inteiro (só contexto, NÃO é a causa da divergência — é ~25x maior que ela na prática).
            # "icms_isento_implicito" é a estimativa (via diff) do ICMS só dos itens isentos, a causa real.
            df_conf = df_conf.rename(columns={"icms_1024": "icms_1024_num",
                                               "icms_isento_implicito": "icms_isento_implicito_num"})
            for col in ("pis_1024", "cofins_1024", "pis_1096", "cofins_1096", "diff_pis", "diff_cofins"):
                df_conf[col] = df_conf[col].apply(lambda v: formatar_moeda(v) if v is not None else "—")
            df_conf["icms_1024"] = df_conf["icms_1024_num"].apply(
                lambda v: formatar_moeda(v) if v is not None else "—")
            df_conf["icms_isento_implicito"] = df_conf["icms_isento_implicito_num"].apply(
                lambda v: formatar_moeda(v) if v is not None else "—")
            df_conf["causa_provavel"] = df_conf["causa_provavel"].fillna("—")
            colunas_exibir = ["cfop", "tipo_operacao", "pis_1024", "cofins_1024", "pis_1096", "cofins_1096",
                               "diff_pis", "diff_cofins", "icms_1024", "icms_isento_implicito", "situacao",
                               "causa_provavel"]
            st.dataframe(df_conf[colunas_exibir], use_container_width=True, hide_index=True)

        # -------------------------------------------------------------------------------------- Detalhar um CFOP
        st.markdown("---")
        st.subheader("🔍 Detalhar um CFOP")
        st.caption(
            "Mostra o insumo bruto por trás da linha acima: o que a Rotina 1024 trouxe por filial (lado "
            "\"1024\") e os itens do Relatório 1096 agrupados por CST, com a faixa de alíquota de PIS/COFINS "
            "usada em cada um (lado \"1096\"). Causa mais comum de divergência: a Rotina 1024 soma o CFOP "
            "inteiro e aplica uma alíquota só (0,65%/3%), mas o 1096 respeita a alíquota de cada item — se "
            "aparecer um CST com aliq_pis/aliq_cofins diferente de 0,65%/3% aqui embaixo (ex.: monofásica, "
            "ST, alíquota zero), é ele que está puxando a diferença."
        )
        cfops_disponiveis = sorted({l["cfop"] for l in linhas_conf})
        cfops_divergentes = sorted({l["cfop"] for l in linhas_conf if l["situacao"] != "OK"})
        cfop_detalhe = st.selectbox(
            "CFOP", cfops_disponiveis,
            index=cfops_disponiveis.index(cfops_divergentes[0]) if cfops_divergentes else 0,
            key="conf_pres_cfop_detalhe",
        )
        detalhe = detalhar_cfop_presumido(session, competencia_id, cfop_detalhe)

        dc1, dc2 = st.columns(2)
        with dc1:
            st.markdown("**Rotina 1024 — por filial**")
            if not detalhe["1024_por_filial"]:
                st.info("Nenhuma linha da Rotina 1024 para este CFOP nesta competência.")
            else:
                df_1024 = pd.DataFrame(detalhe["1024_por_filial"])
                df_1024["valor_contabil"] = df_1024["valor_contabil"].apply(formatar_moeda)
                df_1024["valor_icms"] = df_1024["valor_icms"].apply(formatar_moeda)
                st.dataframe(df_1024, use_container_width=True, hide_index=True)
        with dc2:
            st.markdown("**Relatório 1096 — por CST**")
            if not detalhe["1096_por_cst"]:
                st.info("Nenhum item do Relatório 1096 (saída) para este CFOP nesta competência.")
            else:
                df_1096 = pd.DataFrame(detalhe["1096_por_cst"])
                for col in ("valor_contabil", "valor_pis", "valor_cofins"):
                    df_1096[col] = df_1096[col].apply(formatar_moeda)
                df_1096["aliq_pis"] = df_1096.apply(
                    lambda r: f"{r['aliq_pis_min']:.4%}" if r["aliq_pis_min"] == r["aliq_pis_max"]
                    else f"{r['aliq_pis_min']:.4%} a {r['aliq_pis_max']:.4%}", axis=1,
                )
                df_1096["aliq_cofins"] = df_1096.apply(
                    lambda r: f"{r['aliq_cofins_min']:.4%}" if r["aliq_cofins_min"] == r["aliq_cofins_max"]
                    else f"{r['aliq_cofins_min']:.4%} a {r['aliq_cofins_max']:.4%}", axis=1,
                )
                st.dataframe(
                    df_1096[["cst", "cst_descricao", "n_itens", "valor_contabil", "aliq_pis", "valor_pis",
                              "aliq_cofins", "valor_cofins"]],
                    use_container_width=True, hide_index=True,
                )
