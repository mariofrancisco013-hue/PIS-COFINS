"""
Identidade visual "Sodine" — sessão de continuação de 20/08/2026, a partir do mockup HTML/Tailwind
(`layout_redesign_apura_o_pis_cofins_grupo_sodine.html`) enviado pelo usuário ("também quero ajustar a
identidade visual com base nesse código e html").

Streamlit não renderiza Tailwind/Chart.js — o caminho real (inclusive sugerido dentro do próprio mockup,
no modal "CSS para Streamlit") é extrair a paleta de cores e replicar via CSS injetado + `st.markdown`.
Este módulo é a extensão dessa ideia: não é só um trecho de CSS solto, é um pacote reutilizável (cores +
componentes) importado por toda página que precisar de KPI card, badge de status ou título de seção no
padrão do mockup.

Decisão de escopo (pedido do usuário: "redesenho estrutural completo" + "app inteiro"):
- Cores, tipografia, botões, métricas, tabelas e alertas: aplicados a TODAS as páginas (`inject_main_theme()`
  chamado logo após `require_login()`/`logout_button()` em cada uma).
- Home.py: reestruturada como "Painel Consolidado" — cards de KPI + tabela de competências com badges de
  status, reaproveitando os MESMOS dados que a página já consultava (nenhuma lógica de cálculo nova).
- Páginas de apuração (Lucro Real / Lucro Presumido) e as demais: só reskin (tema + títulos de seção) —
  as abas, tabelas e lógica de cálculo/conferência já implementadas e validadas NÃO foram tocadas.
- NÃO migrei a navegação para `st.navigation()`. O menu automático de páginas (baseado em `app/pages/`)
  continua como está — trocar pra API nova é mudança maior, já sinalizada como opcional no docstring de
  `lib/auth.py` ("é uma mudança maior, mexe em todas as páginas; se quiser isso, é só pedir"). Não decidi
  reabrir essa frente sem confirmação.
- NÃO adicionei gráficos (Chart.js no mockup) — o pedido foi de identidade visual, não de novos dados/
  cálculos agregados; um dashboard com gráficos exigiria rodar a apuração completa de todas as competências
  a cada carregamento da Home, o que é escopo novo (dado + performance), não puramente visual. Fica como
  sugestão para pedido futuro se fizer sentido.

Paleta extraída do mockup (`tailwind.config.colors`):
    sodine.900 = #0B2545 (navy — cor primária, botões/headers)
    sodine.800 = #134074 (navy mais claro — hover)
    sodine.700 = #2E4F85
    brand.accent = #2563EB (azul — links/ícones/badges info)
    brand.emerald = #10B981 (sucesso)
    brand.amber = #F59E0B (atenção)
    brand.rose = #EF4444 (erro/divergência)
    fundo da página = #F8FAFC (slate-50) — já era o `secondaryBackgroundColor` do config.toml, sem mudança.
"""
import streamlit as st

# Paleta central — único lugar que guarda os valores de cor, pra qualquer ajuste futuro de tom não exigir
# caçar hexadecimais espalhados pelas páginas.
NAVY = "#0B2545"
NAVY_LIGHT = "#134074"
NAVY_SOFT = "#2E4F85"
ACCENT = "#2563EB"
EMERALD = "#10B981"
AMBER = "#F59E0B"
ROSE = "#EF4444"
SLATE_BG = "#F8FAFC"
SLATE_BORDER = "#E2E8F0"
SLATE_TEXT = "#1F2937"

_BADGE_VARIANTES = {
    "success": (EMERALD, "#ECFDF5", "#065F46"),
    "warning": (AMBER, "#FFFBEB", "#92400E"),
    "danger": (ROSE, "#FEF2F2", "#991B1B"),
    "info": (ACCENT, "#EFF6FF", "#1E40AF"),
    "neutral": ("#94A3B8", "#F1F5F9", "#475569"),
}

_CSS_MAIN = f"""
<style>
/* Rodapé "Made with Streamlit" — sem função pra quem já está logado no app interno. O menu (⋮) continua
   visível, tem opções úteis (Rerun, Print, Settings). */
footer {{ visibility: hidden; }}

/* Botões — cor primária já vem do primaryColor no .streamlit/config.toml (= {NAVY}, atualizado junto com
   esta identidade); aqui só o hover/sombra, que o tema nativo não cobre. */
.stButton > button[kind="primary"], .stButton > button[kind="primaryFormSubmit"] {{
    transition: all 0.15s ease;
}}
.stButton > button[kind="primary"]:hover, .stButton > button[kind="primaryFormSubmit"]:hover {{
    background-color: {NAVY_LIGHT} !important;
    border-color: {NAVY_LIGHT} !important;
    box-shadow: 0 4px 12px rgba(11, 37, 69, 0.20);
}}

/* Métricas (st.metric) — valor em destaque, no peso/cor do mockup (KPI cards). */
[data-testid="stMetricValue"] {{
    font-weight: 800 !important;
    color: {NAVY} !important;
}}
[data-testid="stMetricLabel"] {{
    font-weight: 600 !important;
    text-transform: uppercase;
    font-size: 0.72rem !important;
    letter-spacing: 0.03em;
    color: #64748B !important;
}}

/* Abas (st.tabs) — aba ativa com sublinhado navy, igual ao destaque de nav do mockup. */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
.stTabs [aria-selected="true"] {{
    color: {NAVY} !important;
    font-weight: 700 !important;
}}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {NAVY} !important; }}

/* Expanders — cabeçalho com leve destaque, mais perto dos "cards" brancos com borda do mockup. */
[data-testid="stExpander"] {{
    border: 1px solid {SLATE_BORDER} !important;
    border-radius: 0.75rem !important;
}}

/* Cabeçalho de tabelas/dataframes — fundo cinza-claro como no mockup (thead bg-slate-100). */
[data-testid="stDataFrame"] thead tr th {{
    background-color: #F1F5F9 !important;
    color: #475569 !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    font-size: 0.72rem !important;
    letter-spacing: 0.02em;
}}

/* Alertas nativos (st.info/success/warning/error) — cantos arredondados iguais aos cards do mockup. */
[data-testid="stAlert"] {{ border-radius: 0.75rem !important; }}
</style>
"""


def inject_main_theme():
    """Chamar uma vez por página (logo após require_login()/logout_button()). Cobre só o conteúdo
    principal — o tema da sidebar/login continua isolado em lib/auth.py (mesma paleta, já atualizada
    pra sodine.900/800 nesta sessão), porque aquele CSS já existia e cobre elementos diferentes
    (stSidebar/stAppViewContainer) sem sobreposição com este."""
    st.markdown(_CSS_MAIN, unsafe_allow_html=True)


def section_title(icon: str, texto: str, badge_texto: str | None = None, badge_variante: str = "neutral"):
    """Título de seção no padrão do mockup: ícone + texto em negrito, com badge opcional à direita
    (ex.: contagem de pendências). Substitui st.subheader() só onde o visual de "card header" faz sentido
    — não é obrigatório trocar todo st.subheader() existente."""
    badge_html = f" {_badge_html(badge_texto, badge_variante)}" if badge_texto else ""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:0.5rem;margin:0.3rem 0 0.6rem 0;">'
        f'<span style="font-size:1.05rem;">{icon}</span>'
        f'<span style="font-weight:700;font-size:1.05rem;color:{SLATE_TEXT};">{texto}</span>'
        f'{badge_html}</div>',
        unsafe_allow_html=True,
    )


def _badge_html(texto: str, variante: str = "neutral") -> str:
    borda, fundo, cor_texto = _BADGE_VARIANTES.get(variante, _BADGE_VARIANTES["neutral"])
    return (
        f'<span style="background-color:{fundo};color:{cor_texto};border:1px solid {borda}33;'
        f'font-size:0.68rem;font-weight:700;padding:0.15rem 0.55rem;border-radius:999px;">{texto}</span>'
    )


def badge(texto: str, variante: str = "neutral"):
    """Pill de status isolado (fora de um section_title), pra usar dentro de tabelas/listas customizadas."""
    st.markdown(_badge_html(texto, variante), unsafe_allow_html=True)


def kpi_card(coluna, label: str, valor: str, sublabel: str = "", variante: str = "light"):
    """Card de KPI no padrão do mockup (canto superior: label; corpo: valor grande; rodapé: sublabel).
    `coluna` é o objeto retornado por st.columns()[i] — chame dentro de `with coluna:` ou passe a coluna
    diretamente (usa coluna.markdown)."""
    if variante == "dark":
        bg = f"linear-gradient(135deg, {NAVY} 0%, {NAVY_LIGHT} 100%)"
        cor_label, cor_valor, cor_sub = "#C7D6EF", "#FFFFFF", "#9FB3D9"
        borda = NAVY_LIGHT
    else:
        bg = "#FFFFFF"
        cor_label, cor_valor, cor_sub = "#64748B", NAVY, "#94A3B8"
        borda = SLATE_BORDER
    coluna.markdown(
        f'<div style="background:{bg};border:1px solid {borda};border-radius:0.85rem;padding:1rem 1.1rem;'
        f'box-shadow:0 1px 2px rgba(15,23,42,0.06);height:100%;">'
        f'<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.03em;'
        f'color:{cor_label};">{label}</div>'
        f'<div style="font-size:1.55rem;font-weight:800;color:{cor_valor};margin-top:0.35rem;">{valor}</div>'
        f'<div style="font-size:0.72rem;color:{cor_sub};margin-top:0.3rem;">{sublabel}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
