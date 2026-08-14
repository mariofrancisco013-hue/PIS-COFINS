# Apuração PIS/COFINS — Grupo Sodine

Plataforma de apuração de PIS/COFINS, construída em 14/08/2026 (Supabase + Streamlit + GitHub), na mesma
arquitetura do projeto "Apuração ICMS". Módulo em desenvolvimento: **PIS/COFINS Lucro Real** (regime
não-cumulativo, Leis nº 10.637/2002 e 10.833/2003). Módulo futuro: **PIS/COFINS Lucro Presumido** (regime
cumulativo) — o cadastro de empresas já tem o campo `regime` para rotear cada empresa para o módulo certo
quando esse módulo for construído.

A metodologia completa (mapeamento do Relatório 1096, listas de CFOP por linha da apuração, tabela CST,
fórmula validada contra a planilha real do usuário, pontos em aberto) está documentada no projeto Claude
"PIS/COFINS" (`claude/metodologia-pis-cofins-lucro-real.md`) — leia antes de mexer no código.

## Arquitetura
- **Banco**: Postgres via Supabase, acessado por conexão direta (SQLAlchemy + psycopg2) — não usa a API
  REST/PostgREST do Supabase. Funciona sem mudança de código com qualquer Postgres gerenciado, bastando
  trocar `DATABASE_URL`. Pode apontar para o **mesmo** projeto Supabase do módulo ICMS (tabelas com nomes
  diferentes, sem conflito) ou para um projeto novo — decisão livre, o código não assume nenhum dos dois.
- **Autenticação**: Supabase Auth (login/senha). Única parte do app específica do Supabase.
- **Frontend**: Streamlit.
- **Todos os usuários logados têm o mesmo nível de acesso** (sem perfis admin/analista, mesma decisão do
  módulo ICMS).

## Setup

1. Crie um projeto no Supabase (banco + Auth) — ou reuse o mesmo do módulo ICMS.
2. Rode a migração SQL: `sql/001_schema.sql` no SQL Editor do Supabase.
3. Copie `.env.example` → `.env` (para rodar scripts localmente) e `.streamlit/secrets.toml.example` →
   `.streamlit/secrets.toml` (para rodar o app), preenchendo `DATABASE_URL`, `SUPABASE_URL` e
   `SUPABASE_ANON_KEY`.
4. Crie os usuários da equipe no painel do Supabase (Authentication → Users).
5. Instale as dependências: `pip install -r requirements.txt`.
6. Carregue os dados de referência:
   ```
   python scripts/seed_empresas.py
   python scripts/seed_cfop_pis_cofins.py
   python scripts/seed_cst_pis_cofins.py
   ```
7. Importe um período (Relatório 1096 de Entrada e/ou Saída):
   ```
   python scripts/import_relatorios.py --empresa-cnpj 07.342.785/0001-20 --ano 2026 --mes 7 \
       --entrada "1096 - Entradas.xlsx" --saida "1096 - saidas.xlsx"
   ```
   Use `--substituir` para reimportar um período (relatório corrigido) sem duplicar itens.
8. Rode o app: `streamlit run app/Home.py`.
9. Na página **PIS/COFINS Lucro Real**, aba **Ajustes Manuais**, lance Aluguéis (Prédios/Máquinas) e
   Depreciação do mês (linhas 5.3/5.4/5.6 da apuração) — informe só a base, o app calcula o crédito de
   PIS (1,65%) e COFINS (7,60%) automaticamente.
10. Clique em **Calcular apuração** na aba **Apuração** para gerar o resultado (débito, crédito, saldo e
    líquido a pagar em DARF).

## O que está pronto nesta versão (v1, 14/08/2026)

- Importação do Relatório 1096 (Entrada e Saída), com detecção de CST/CFOP não cadastrados
  (inconsistência pendente, não ignorado silenciosamente).
- Cálculo automático do débito (Saída) e crédito (Entrada) a partir dos itens do relatório, agrupados por
  CFOP nas linhas 1.1/1.2/1.4/1.6 (débito) e 5.1/5.2/5.5/5.7/5.8 (crédito — 5.2 Energia Elétrica via CFOP
  1253, achado testando o arquivo real de julho/2026, ver metodologia).
- Lançamento manual de créditos de Aluguéis (Prédios / Máquinas e Equipamentos) e Depreciação (linhas
  5.3/5.4/5.6), com cálculo automático do PIS/COFINS a partir da base informada.
- Apuração final (saldo devedor/credor, líquido a pagar em DARF por PIS e por COFINS), com saldo credor do
  período anterior informado manualmente (linhas 8.1/8.2).
- Validado por conferência aritmética contra a planilha real do usuário (`PIS-COFINS - LUCRO REAL.xls`,
  aba `PC`) para os meses de abril/maio/junho de 2026 — ver metodologia no projeto para o detalhe da
  conferência.

## Pontos em aberto (ver `claude/metodologia-pis-cofins-lucro-real.md` no projeto para detalhes)

- Sem granularidade de NF: o Relatório 1096 (export "Report") não traz o número da nota fiscal — só o
  relatório impresso/agrupado traz. Não há tela "por NF" como no módulo ICMS Normal.
- Linhas fora do escopo desta versão, ficam zeradas/manuais na apuração: 1.3 (serviços), 1.5 (aluguel
  recebido), 3.x (receitas financeiras — alíquota reduzida 0,65%/4%), 5.9 (fretes Supply Log), e as
  exclusões que dependem de ICMS/IPI/exportação (2.3/2.4/2.6/6.3/6.4/6.5/6.6).
- Saldo credor do período anterior não encadeia automaticamente entre competências — precisa ser digitado
  a cada mês (mesmo ponto em aberto do módulo ICMS, "linha 09").
- Módulo PIS/COFINS Lucro Presumido: não construído ainda.
