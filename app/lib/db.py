"""
Camada de acesso ao banco — conexão direta de Postgres via SQLAlchemy/psycopg2.

Decisão de arquitetura (mantida da tentativa anterior, ver claude/arquitetura-plataforma.md no projeto):
NÃO usar supabase-py / PostgREST para dados. Isso deixa o código agnóstico de provedor — funciona sem
nenhuma mudança com Supabase, Neon, RDS ou qualquer Postgres gerenciado, bastando trocar DATABASE_URL.
A autenticação (login/senha) é a única parte específica do Supabase — ver app/lib/auth.py.

CORREÇÃO DE PERFORMANCE (05/08/2026): a versão anterior usava NullPool ("sem pool — abre uma conexão
física nova a cada query, fecha depois"). Isso foi escolhido por cautela, mas na prática deixa CADA
consulta pagando o custo inteiro de handshake TCP+TLS+autenticação Postgres — no Streamlit Cloud, com o
processo do app ficando de pé entre interações, isso deixa tudo visivelmente lento. Trocado para um pool
pequeno (QueuePool) que reaproveita conexões entre reruns do Streamlit, e a criação do engine agora usa
st.cache_resource quando disponível (mais seguro contra condição de corrida entre sessões simultâneas do
que a variável global simples de antes).

CORREÇÃO "IDLE IN TRANSACTION" (06/08/2026): cada página do Streamlit chama `get_session()` uma vez e usa
essa mesma sessão o script inteiro, mas nunca chama `session.close()` no fim — o script simplesmente
termina, e o objeto Session vira lixo. O problema é que uma ORM Session do SQLAlchemy tem referências
internas cíclicas, então o coletor de lixo do Python não fecha a conexão/transação na hora — ela pode
ficar "pendurada" (estado "idle in transaction" no Postgres) por muito tempo, até o GC cíclico rodar. Isso
já travou duas vezes um `alter table` no SQL Editor do Supabase (a conexão pendurada segurava um lock na
tabela e o painel desistia por timeout). Corrigido aqui: o engine usa isolation_level="AUTOCOMMIT" — cada
comando já vira sua própria transação, que fecha sozinha assim que termina, então não existe mais como uma
conexão ficar "idle in transaction" nem por engano. Não muda nada no comportamento do app: todo ponto do
código que grava dado já chamava `session.commit()` explicitamente antes disso (e não há nenhum
`session.rollback()` no projeto que dependesse do modo anterior).
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_engine = None
_SessionLocal = None


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        # Streamlit Community Cloud injeta st.secrets; ao rodar scripts fora do Streamlit, usa env var.
        try:
            import streamlit as st
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            pass
    if not url:
        raise RuntimeError(
            "DATABASE_URL não configurado. Defina a variável de ambiente ou o secret do Streamlit "
            "com a connection string direta de Postgres (Project Settings → Database → Connection "
            "string → URI, não a API REST). Recomendado: use a connection string do Session Pooler "
            "(Project Settings → Database → Connection Pooling), não a conexão direta — a direta só "
            "responde por IPv6 e a maioria das hospedagens (incluindo Streamlit Community Cloud) não "
            "tem saída IPv6."
        )
    return url


def _create_engine():
    return create_engine(
        get_database_url(),
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,   # recicla conexões a cada 30min — evita conexão "morta" pelo pooler do Supabase
        pool_pre_ping=True,  # testa a conexão antes de usar; reabre sozinho se caiu
        isolation_level="AUTOCOMMIT",  # nunca deixa uma conexão "idle in transaction" pendurada (ver docstring)
    )


def get_engine():
    global _engine
    try:
        import streamlit as st
        # st.cache_resource garante uma única instância por processo mesmo com várias sessões/threads
        # do Streamlit rodando ao mesmo tempo — mais seguro que a variável global simples abaixo.
        cached = st.cache_resource(_create_engine, show_spinner=False)
        return cached()
    except Exception:
        pass
    if _engine is None:
        _engine = _create_engine()
    return _engine


def get_session():
    """CORREÇÃO "TimeoutError: QueuePool limit... connection timed out" (produção, sessão de continuação,
    21/08/2026 à noite — erro ocorreu em `Home.py`, uma página que este trabalho nem tocou, confirmando que
    a causa é estrutural/pré-existente, não algo introduzido pelas features desta sessão): TODA página do
    app chama `get_session()` uma única vez por execução do script (`Home.py`, `1_Importar_Relatorios.py`,
    `2_PIS_COFINS_Lucro_Real.py`, `3_Empresas.py`, `4_CFOP_CST.py`, `5_PIS_COFINS_Lucro_Presumido.py`) e
    NUNCA chama `session.close()` no fim (ver docstring do módulo, comentário "IDLE IN TRANSACTION" de
    06/08/2026 — já sabia disso, mas só tratou o sintoma de transação pendurada via AUTOCOMMIT, não o
    vazamento de conexão em si). Antes desta correção, cada nova chamada criava um `Session` novo (via
    `_SessionLocal()`), que assim que executa a primeira query fica com uma conexão do pool amarrada até
    o objeto Session ser coletado pelo GC — e como `Session` tem referências cíclicas internas, o
    refcounting do Python não libera na hora, só o GC cíclico (que roda esporadicamente). Streamlit reexecuta
    o script inteiro a CADA interação (clique, digitação, etc.) — então cada rerun deixava um Session/conexão
    "no limbo" esperando o GC, e com pool pequeno (`pool_size=5, max_overflow=5` — só 10 conexões) e mais de
    um usuário/aba ativa ao mesmo tempo, o pool esgotava antes do GC dar conta, gerando exatamente esse
    `TimeoutError`.

    CORRIGIDO reaproveitando a MESMA Session entre reruns do Streamlit via `st.session_state` (que já é,
    por natureza, escopado por aba/sessão do navegador — não é compartilhado entre usuários/abas
    diferentes): em vez de 1 conexão vazada por rerun, agora é NO MÁXIMO 1 conexão mantida por aba ativa,
    reaproveitada entre reruns em vez de acumular. `session.rollback()` defensivo ao reaproveitar (mesmo sob
    AUTOCOMMIT, o `Session` do SQLAlchemy pode marcar sua transação lógica como "precisa rollback" depois de
    um erro no meio de uma query anterior — sem isso, uma falha num rerun deixaria a mesma sessão inutilizável
    nos reruns seguintes). Fora do Streamlit (scripts/testes que chamam `get_session()` direto), cai no
    mesmo fallback de `Session` global de sempre (`_SessionLocal`), sem mudança de comportamento aí.

    NÃO precisou tocar nenhuma página (`Home.py`, `2_PIS_COFINS_Lucro_Real.py` incluído) — a correção é só
    aqui dentro, e não muda nenhuma query nem resultado, só QUANDO a conexão é devolvida ao pool."""
    try:
        import streamlit as st
        if "_db_session" not in st.session_state or st.session_state["_db_session"] is None:
            st.session_state["_db_session"] = sessionmaker(bind=get_engine())()
        else:
            try:
                st.session_state["_db_session"].rollback()
            except Exception:
                # Sessão realmente morta (ex.: conexão caiu e pool_pre_ping não deu conta) -- descarta e
                # cria uma nova, em vez de propagar erro de uma sessão zumbi pro resto da página.
                st.session_state["_db_session"] = sessionmaker(bind=get_engine())()
        return st.session_state["_db_session"]
    except Exception:
        pass
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()
