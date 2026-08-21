# Apuração PIS/COFINS — Grupo Sodine

Plataforma de apuração de PIS/COFINS, construída em 14/08/2026 (Supabase + Streamlit + GitHub), na mesma
arquitetura do projeto "Apuração ICMS". Módulo em desenvolvimento: **PIS/COFINS Lucro Real** (regime
não-cumulativo, Leis nº 10.637/2002 e 10.833/2003). Módulo futuro: **PIS/COFINS Lucro Presumido** (regime
cumulativo) — o cadastro de empresas já tem o campo `regime` para rotear cada empresa para o módulo certo
quando esse módulo for construído.

A metodologia completa (fonte de dados, listas de CFOP por linha da apuração, tabela CST, fórmula validada,
pontos em aberto) está documentada no projeto Claude "PIS/COFINS"
(`claude/metodologia-pis-cofins-lucro-real.md`) — leia antes de mexer no código.

## ⚠️ Mudança de metodologia (v2, 14/08/2026 à noite)

A apuração passou a ser feita **por grupo econômico** (CNPJ raiz — matriz + filiais consolidadas), não mais
por uma empresa isolada, e a fonte **primária** do cálculo passou a ser a **Rotina 1024** (Livro RAICMS
Modelo P9, .pdf), não mais o Relatório 1096 direto. Confirmado com o usuário: a base do PIS/COFINS por CFOP
é `Valor Contábil − ICMS destacado` (Rotina 1024), somada entre todas as filiais do grupo. O Relatório 1096
continua sendo importado, mas agora só para **conferência** por CFOP (aba "Conferência 1024×1096") e para a
checagem de CST fora da tabela oficial. Se você já rodou a v1 (empresa única, 1096 como fonte direta), **rode
a migração `sql/002_multifilial_1024.sql`** antes de continuar usando o app — ver "Setup" abaixo.

## Arquitetura
- **Banco**: Postgres via Supabase, acessado por conexão direta (SQLAlchemy + psycopg2) — não usa a API
  REST/PostgREST do Supabase. Funciona sem mudança de código com qualquer Postgres gerenciado, bastando
  trocar `DATABASE_URL`. Pode apontar para o **mesmo** projeto Supabase do módulo ICMS (tabelas com nomes
  diferentes, sem conflito) ou para um projeto novo — decisão livre, o código não assume nenhum dos dois.
- **Autenticação**: Supabase Auth (login/senha). Única parte do app específica do Supabase.
- **Frontend**: Streamlit.
- **Todos os usuários logados têm o mesmo nível de acesso** (sem perfis admin/analista, mesma decisão do
  módulo ICMS).

## Setup (instalação nova)

1. Crie um projeto no Supabase (banco + Auth) — ou reuse o mesmo do módulo ICMS.
2. Rode as migrações SQL, NESTA ORDEM, no SQL Editor do Supabase: `sql/001_schema.sql` e depois
   `sql/002_multifilial_1024.sql`. Se você já tinha o `001` rodado de uma versão anterior (v1), rode só o
   `002` — ele é seguro de rodar mesmo com dados já importados (não apaga nada, só adapta o schema).
3. Copie `.env.example` → `.env` (para rodar scripts localmente) e `.streamlit/secrets.toml.example` →
   `.streamlit/secrets.toml` (para rodar o app), preenchendo `DATABASE_URL`, `SUPABASE_URL` e
   `SUPABASE_ANON_KEY`.
4. Crie os usuários da equipe no painel do Supabase (Authentication → Users).
5. Instale as dependências: `pip install -r requirements.txt` (inclui `pdfplumber`, novo nesta versão, para
   ler o PDF da Rotina 1024).
6. Carregue os dados de referência:
   ```
   python scripts/seed_empresas.py
   python scripts/seed_cfop_pis_cofins.py
   python scripts/seed_cst_pis_cofins.py
   ```
7. Rode o app: `streamlit run app/Home.py`.
8. Na página **Importar Relatórios**: escolha o **grupo** (CNPJ raiz) e o período, veja a tabela de status
   de cada filial do grupo, escolha uma filial e importe a **Rotina 1024** dela (obrigatório — é o que
   alimenta o cálculo) e, se quiser, o **Relatório 1096** (Entrada/Saída — só conferência). Repita para cada
   filial do grupo antes de calcular a apuração consolidada.
9. Na página **PIS/COFINS Lucro Real**, aba **Ajustes Manuais**, lance Aluguéis (Prédios/Máquinas) e
   Depreciação do mês (linhas 5.3/5.4/5.6 da apuração) — informe só a base, o app calcula o crédito de
   PIS (1,65%) e COFINS (7,60%) automaticamente.
10. Clique em **Calcular apuração** na aba **Apuração** para gerar o resultado consolidado (débito, crédito,
    saldo e líquido a pagar em DARF, somando todas as filiais do grupo já importadas).

## O que está pronto nesta versão (v2, 14/08/2026)

- Importação da Rotina 1024 (PDF do Livro RAICMS Modelo P9), uma por filial, com leitura automática por
  CFOP (reaproveita o parser já validado do módulo ICMS).
- Apuração por **grupo** (CNPJ raiz): todas as filiais do grupo importadas na mesma competência são somadas
  automaticamente por CFOP antes do cálculo — sem precisar consolidar manualmente.
- Base de cálculo por CFOP = Valor Contábil − ICMS destacado (Rotina 1024), agrupada nas linhas 1.1/1.2/1.4/
  1.6 (débito) e 5.1/5.2/5.5/5.7/5.8 (crédito) — já embute a exclusão do ICMS destacado (linhas 2.3/6.4),
  sem precisar de uma linha de exclusão manual separada.
- Importação do Relatório 1096 (Entrada e Saída) mantida, agora como **conferência**: aba "Conferência
  1024×1096" compara por CFOP o resultado da Rotina 1024 contra a soma direta de PIS/COFINS do 1096,
  sinalizando divergência (tolerância R$ 1,00) ou CFOPs que só aparecem numa das duas fontes.
- Detecção de CST/CFOP não cadastrados (inconsistência pendente, não ignorado silenciosamente), tanto pela
  Rotina 1024 (bloqueia o cálculo daquele CFOP) quanto pelo 1096 (só conferência).
- Lançamento manual de créditos de Aluguéis (Prédios / Máquinas e Equipamentos) e Depreciação (linhas
  5.3/5.4/5.6), com cálculo automático do PIS/COFINS a partir da base informada.
- Apuração final (saldo devedor/credor, líquido a pagar em DARF por PIS e por COFINS), com saldo credor do
  período anterior informado manualmente (linhas 8.1/8.2).

## Pontos em aberto (ver `claude/metodologia-pis-cofins-lucro-real.md` no projeto para detalhes)

- Linhas fora do escopo desta versão, ficam zeradas/manuais na apuração: 1.3 (serviços), 1.5 (aluguel
  recebido), 3.x (receitas financeiras — alíquota reduzida 0,65%/4%), 5.9 (fretes Supply Log), e as
  exclusões que a Rotina 1024 não cobre (2.4 ICMS Substituição, 2.6/6.6 Exportação, 6.3 IPI, 6.5 Entradas
  isentas fora do CST).
- Saldo credor do período anterior não encadeia automaticamente entre competências — precisa ser digitado
  a cada mês (mesmo ponto em aberto do módulo ICMS, "linha 09").
- Módulo PIS/COFINS Lucro Presumido: não construído ainda — mesma base (1024, Valor Contábil − ICMS), mas
  crédito de entrada restrito a devolução de venda (confirmado com o usuário em 14/08/2026), sem crédito
  amplo sobre compras (regime cumulativo).
