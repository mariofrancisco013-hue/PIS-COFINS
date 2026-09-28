"""
Cadastro editável dos NCMs alcançados pela Lei Complementar 224/2025 (incidência residual de PIS/COFINS
sobre produtos hoje isentos, CST 6/7 de saída) — tabela `ncms_lc224_pc`, criada em
`sql/009_ncms_lc224_pc.sql` (20/08/2026) para servir de fonte editável do cálculo sem precisar mexer em
código: usada por `calcular_apuracao_pc` (linha "4", Lucro Real) e `calcular_apuracao_pc_presumido` (linha
"3.1", Lucro Presumido).

Este módulo dá esse cadastro uma TELA (sessão de continuação, 28/09/2026 — pedido do usuário: "crie uma aba
dentro de regra cst para que eu possa adicionar ou excluir as informações do sql 09 sempre que necessario"),
como uma 4ª sub-aba dentro de "🔖 Regras de CST" nas duas páginas de Apuração, no mesmo padrão de
`st.data_editor` (grade tipo planilha, `num_rows="dynamic"`) já usado pelas outras 3 sub-abas
(`cst_regras_pc.salvar_regras_cfop/_ncm/_alerta`) — em vez de precisar abrir o SQL Editor do Supabase e
rodar um `insert`/`update`/`delete` manual toda vez que um NCM precisar ser incluído, corrigido ou
removido.

Por que um módulo bespoke, e não reaproveitar `cst_regras_pc._salvar_regra_generica`: naquela função,
`colunas_chave` (identidade da linha nova + validação) é diferente de `colunas_conflito` (o que a unique
constraint da tabela realmente cobre) porque só "observacao" é editável sem reidentificar a linha — CST é o
"valor" da regra, CFOP/NCM+direção é a identidade. Aqui é o oposto: a identidade da tabela é (ncm, regime)
— `regime` nunca vem da grade (é fixo por página, ver abaixo) — mas aliq_pis/aliq_cofins/ativo/observacao
são TODAS colunas de valor, livremente editáveis numa linha já existente sem trocar sua identidade. Forçar
isso no formato genérico exigiria mais código de adaptação do que escrever a versão direta abaixo.

Uma linha por (ncm, regime) — alíquotas diferem entre Presumido e Real (ver unique constraint da tabela em
sql/009). Cada página de Apuração mostra e edita só o regime dela (Lucro Real sempre passa regime="real",
Lucro Presumido sempre regime="presumido") — diferente das outras 3 sub-abas de Regras de CST, que são
globais entre os dois regimes.
"""
from sqlalchemy import text
import pandas as pd

COLUNAS_EDITAVEIS = ["ncm", "aliq_pis", "aliq_cofins", "ativo", "observacao"]


def listar_ncms_lc224(session, regime):
    rows = session.execute(text("""
        select id, ncm, aliq_pis, aliq_cofins, ativo, observacao, created_at
        from ncms_lc224_pc where regime = :regime order by ncm
    """), {"regime": regime}).mappings().all()
    return rows


def _tipar(col, v):
    if v is None:
        return None
    if col in ("aliq_pis", "aliq_cofins"):
        return float(v)
    if col == "ativo":
        return bool(v)
    if col == "ncm":
        return str(v).strip()
    return v


def salvar_ncms_lc224(session, regime, df_original, df_editado):
    """Linha nova (sem id) insere (ou atualiza por upsert, se o NCM já existir para este regime — mesmo
    padrão de "cadastrar de novo com um valor diferente atualiza" das outras 3 sub-abas); linha removida na
    grade (ícone de lixeira) EXCLUI de verdade a linha do banco — atende ao pedido do usuário de poder
    "adicionar ou excluir" direto na tela; qualquer coluna de uma linha EXISTENTE que mudou (inclusive o
    próprio NCM digitado, não só alíquota/observação) é atualizada por id. `regime` é sempre o parâmetro
    fixo da página que chamou, nunca uma coluna da grade. Retorna {"incluidos", "removidos", "atualizados"}.

    Para desativar um NCM SEM apagar o cadastro/histórico (mantendo rastreável por que ele não entra mais no
    cálculo), desmarque a coluna "Ativo" em vez de excluir a linha — mesmo padrão documentado no comentário
    da coluna `ativo` em sql/009_ncms_lc224_pc.sql. `calcular_apuracao_pc`/`_presumido` só consideram linhas
    com `ativo = true` (ver `_carregar_ncms_lc224` nos dois módulos de cálculo)."""
    ids_originais = set(df_original["id"].dropna().astype(int)) if not df_original.empty else set()
    ids_editados = set(df_editado["id"].dropna().astype(int)) if "id" in df_editado.columns else set()

    removidos = ids_originais - ids_editados
    for rid in removidos:
        session.execute(text("delete from ncms_lc224_pc where id = :id"), {"id": int(rid)})

    atualizados = 0
    if not df_original.empty:
        orig = df_original.set_index("id")
        for rid in (ids_originais & ids_editados):
            linha_edit = df_editado[df_editado["id"] == rid]
            if linha_edit.empty:
                continue
            linha_edit = linha_edit.iloc[0]
            valores, mudou = {}, False
            for col in COLUNAS_EDITAVEIS:
                v_orig = orig.loc[rid, col] if col in orig.columns else None
                v_edit = linha_edit.get(col)
                v_orig_norm = None if pd.isna(v_orig) else v_orig
                v_edit_norm = None if pd.isna(v_edit) else v_edit
                if v_orig_norm != v_edit_norm:
                    mudou = True
                valores[col] = _tipar(col, v_edit_norm)
            if mudou:
                # NCM não pode ficar vazio numa linha existente — se a edição deixou em branco, mantém o
                # valor antigo em vez de gravar um NCM vazio (mesma cautela do "valido" na inclusão abaixo).
                if not valores.get("ncm"):
                    valores["ncm"] = orig.loc[rid, "ncm"]
                if valores.get("aliq_pis") is None or valores.get("aliq_cofins") is None:
                    continue
                if valores.get("ativo") is None:
                    valores["ativo"] = bool(orig.loc[rid, "ativo"])
                sets_sql = ", ".join(f"{c} = :{c}" for c in COLUNAS_EDITAVEIS)
                session.execute(text(f"update ncms_lc224_pc set {sets_sql} where id = :id"),
                                 {**valores, "id": int(rid)})
                atualizados += 1

    incluidos = 0
    novas = df_editado[df_editado["id"].isna()] if "id" in df_editado.columns else df_editado
    for _, row in novas.iterrows():
        ncm = row.get("ncm")
        aliq_pis = row.get("aliq_pis")
        aliq_cofins = row.get("aliq_cofins")
        if pd.isna(ncm) or not str(ncm).strip() or pd.isna(aliq_pis) or pd.isna(aliq_cofins):
            continue
        ativo = row.get("ativo")
        ativo = True if pd.isna(ativo) else bool(ativo)
        observacao = row.get("observacao")
        observacao = None if pd.isna(observacao) or not str(observacao).strip() else str(observacao)
        session.execute(text("""
            insert into ncms_lc224_pc (ncm, regime, aliq_pis, aliq_cofins, ativo, observacao)
            values (:ncm, :regime, :aliq_pis, :aliq_cofins, :ativo, :obs)
            on conflict (ncm, regime) do update
                set aliq_pis = excluded.aliq_pis, aliq_cofins = excluded.aliq_cofins,
                    ativo = excluded.ativo, observacao = excluded.observacao
        """), {"ncm": str(ncm).strip(), "regime": regime, "aliq_pis": float(aliq_pis),
               "aliq_cofins": float(aliq_cofins), "ativo": ativo, "obs": observacao})
        incluidos += 1

    session.commit()
    return {"incluidos": incluidos, "removidos": len(removidos), "atualizados": atualizados}
