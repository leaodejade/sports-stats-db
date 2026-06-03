# ⚽ Sports Stats DB

Base de dados local e estruturada para **estatísticas de futebol** (via
[Understat](https://understat.com), usando o pacote
[`understatAPI`](https://github.com/collinb9/understatAPI)), com arquitetura já
preparada para **expansão futura para tênis**.

O foco é montar um banco relacional limpo e reutilizável para análise de
xG / xGA / xA, over/under-performance, forma recente e comparação entre
resultado real e resultado esperado — sem scraping agressivo.

---

## Objetivo

Armazenar e analisar, de forma reproduzível e incremental:

- Ligas, temporadas, times e jogadores
- Partidas, com placar real **e** xG
- Estatísticas por time (xG, xGA, npxG, PPDA, deep, xPTS) por partida e por temporada
- Estatísticas por jogador (xG, xA, gols, assistências, npxG, xGChain/xGBuildup)
- Chutes/finalizações (xG por chute, coordenadas, situação, resultado)
- Classificação (standings) e forma recente
- Rastreabilidade da origem dos dados (`data_sources`) e logs de ingestão

A estrutura de tênis (jogadores, torneios, partidas, rankings, superfícies,
estatísticas de saque/devolução) já existe como **schema dormente** — as tabelas
são criadas, mas ainda não há coletor.

---

## Arquitetura

Pipeline em camadas, com responsabilidade única por módulo:

```
collector  ->  transformer  ->  repository / service  ->  analysis
(raw JSON)     (DTOs Pydantic)   (upsert idempotente)      (DataFrames)
```

```
sports-stats-db/
├── main.py                  # CLI (Typer)
├── requirements.txt
├── .env.example
├── pytest.ini
├── data/
│   ├── raw/                 # JSON bruto salvo por coletor/entidade (cache local)
│   └── processed/           # banco SQLite (sports.db)
├── notebooks/
├── src/
│   ├── collectors/          # busca + cache + rate limit (BaseCollector, Understat)
│   ├── transformers/        # raw -> DTOs validados (coerção de tipos defensiva)
│   ├── database/            # engine, sessão, init/seed do schema
│   ├── models/              # schema SQLAlchemy 2.0 (football.py, tennis.py)
│   ├── services/            # reference + repository + IngestionService (orquestra)
│   ├── analysis/            # consultas analíticas -> pandas
│   └── utils/               # config (.env), logging, cache
└── tests/
```

**Por que essa separação?** O coletor só busca e persiste o JSON cru; o
transformer normaliza (Understat devolve quase tudo como string); o repositório
faz *upsert* idempotente; a análise é somente leitura. O `IngestionService`
recebe o coletor por injeção de dependência — então toda a ingestão é testada
sem rede.

### Schema (resumo)

Futebol: `sports`, `countries`, `competitions`, `seasons`, `teams`, `players`,
`matches`, `match_team_stats`, `match_player_stats`, `shots`, `standings`,
`player_season_stats`, `data_sources`, `ingestion_logs`.

Apostas / modelagem: `bookmakers`, `markets`, `odds_snapshots` (histórico),
`current_odds` (última cotação), `market_results` (liquidação por mercado),
`predictions` (saída de modelo versionada), `simulated_bets`,
`bankroll_transactions`, `bet_decisions` (auditoria de backtest),
`prematch_features` (features pré-jogo sem vazamento), `team_aliases` (dedupe),
`match_context` e `fundamental_notes` (árbitro/clima/escalações estruturadas).

Tênis: `tennis_surfaces`, `tennis_players`, `tennis_tournaments`,
`tennis_matches`, `tennis_match_stats`, `tennis_rankings`.

> Nota de design: `player_season_stats` e `standings` guardam agregados de
> temporada (1 requisição por liga/temporada cada). `match_player_stats` e
> `shots` só são preenchidos na ingestão profunda (`--with-shots`), que custa
> ~2 requisições por partida.
>
> ⚠️ **Vazamento:** `matches.forecast_w/d/l` é uma **retrodição pós-jogo** do
> Understat (derivada do xG das finalizações da própria partida). **Nunca** use
> como feature pré-jogo nem em backtest de apostas. Para previsões de modelo use
> a tabela `predictions`; para features pré-jogo use `prematch_features`
> (construída só com dados anteriores ao kickoff e protegida por teste
> anti-vazamento).

---

## Instalação

Requisitos: **Python 3.11+**.

### Rodar em outra máquina (do zero)

Clone o repositório e rode **um comando**:

```powershell
# Windows (PowerShell)
git clone https://github.com/leaodejade/sports-stats-db.git
cd sports-stats-db
./scripts/setup.ps1
```

```bash
# Linux/macOS
git clone https://github.com/leaodejade/sports-stats-db.git
cd sports-stats-db
bash scripts/setup.sh      # ou: make setup
```

O script cria o `.venv`, instala o pacote, gera o `.env` e aplica as migrations.
Depois, ative o ambiente e **popule o banco com um comando**:

```bash
sports-stats --help
sports-stats bootstrap                                   # EPL 2021-2023 + features
sports-stats bootstrap --leagues all --from 2019 --to 2023   # 6 ligas, 5 temporadas
```

O `bootstrap` ingere várias ligas × temporadas e já constrói as features
pré-jogo, de uma vez. (Para uma liga/temporada só: `sports-stats
ingest-understat --league EPL --season 2023`.)

### Instalação manual (equivalente)

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"          # +"[postgres]" para o driver do PostgreSQL
cp .env.example .env             # Windows: copy .env.example .env
alembic upgrade head             # cria o schema (caminho oficial)
```

`pip install -e .` instala o pacote e o comando de CLI `sports-stats`. Os
defaults já funcionam com SQLite em `data/processed/sports.db`; ajuste o `.env`
se quiser.

> **Rede corporativa / erro de SSL ao coletar:** se a coleta do Understat
> falhar com `CERTIFICATE_VERIFY_FAILED`, sua rede faz inspeção de TLS. Aponte o
> certificado da empresa via variável de ambiente, sem desabilitar verificação:
> `setx REQUESTS_CA_BUNDLE "C:\caminho\corp-ca.pem"` (Windows) /
> `export REQUESTS_CA_BUNDLE=/caminho/corp-ca.pem` (Linux). Os dados já
> coletados ficam em `data/raw/` e são reutilizados (cache), então a coleta só
> ocorre uma vez por liga/temporada.

### Suporte a PostgreSQL

O projeto suporta PostgreSQL caso deseje utilizá-lo em vez do SQLite padrão.
Para começar com Postgres em ambiente de desenvolvimento, inicie o container:

```bash
docker-compose up -d
```

Então, atualize seu `.env` com a seguinte linha:

```env
DATABASE_URL=postgresql+psycopg://devuser:devpassword@localhost/sportsdb
```

Após isso, você pode rodar os comandos `alembic upgrade head` e `python main.py init-db` normalmente.

---

## Uso (CLI)

```bash
# 1. Aplicar as migrations do banco de dados (Caminho oficial)
alembic upgrade head

# 1.1 Criar o banco e as tabelas (+ seed de referência) para desenvolvimento
python main.py init-db

# 2. Ingerir uma liga + temporada do Understat
python main.py ingest-understat --league EPL --season 2023
#    ingestão profunda (chutes + escalações; mais lento):
python main.py ingest-understat --league EPL --season 2023 --with-shots

# 3. Consultas
python main.py team-stats   --team "Arsenal" --season 2023
python main.py player-stats --player "Erling Haaland"
python main.py xg-table     --league EPL --season 2023
```

Comandos extras:

```bash
python main.py team-xg          --league EPL --season 2023 --metric xg|xga|diff
python main.py top-players      --metric xg|xa|over|under --league EPL --season 2023 -n 15
python main.py form             --team "Manchester City" --season 2023 --n 5
python main.py real-vs-expected --league EPL --season 2023
```

Ligas suportadas pelo Understat: `EPL`, `La_liga`, `Bundesliga`, `Serie_A`,
`Ligue_1`, `RFPL`. Temporada = ano de início (ex.: `2023` = 2023/24).

---

## Camada de apostas e modelagem

O banco serve como **camada de persistência** para um sistema externo que
scrapeia odds e roda os modelos. Esse sistema grava odds, predições e resultados
— por código (importando `src.services.betting_repository`) ou via **JSON**
(útil para sistemas em outra linguagem):

```bash
python main.py ingest-odds-json        --file odds.json
python main.py ingest-prediction-json  --file predictions.json
python main.py ingest-results-json     --file results.json
```

Formato (resumo): cada fixture é identificado por `home`, `away`, `league`,
`season`; veja os docstrings em `src/services/json_ingest.py`. Exemplo de odds:

```json
[{"home": "Arsenal", "away": "Chelsea", "league": "EPL", "season": "2023",
  "odds": [{"bookmaker": "Pinnacle", "market": "1x2", "selection": "home",
            "odd": 2.10, "is_closing": true}]}]
```

Avaliação (somente leitura — nada é apostado de verdade):

```bash
python main.py backtest  --model poisson --threshold 0.05 --price closing
python main.py calibrate --model poisson --by league
python main.py best-odds
python main.py clv
python main.py pnl
```

- **backtest** — aposta de valor (`EV = prob*odd-1 > limiar`) sobre
  `predictions` × odds × `market_results`; imprime ROI/lucro/acerto/drawdown e
  recortes por liga, mercado e faixa de odd. Toda decisão (inclusive recusada,
  com motivo) é auditável em `bet_decisions`.
- **calibrate** — Brier, log-loss e tabela de confiabilidade por liga/mercado.
- **clv / pnl / best-odds** — Closing Line Value, P&L da banca e melhor preço
  por mercado.

### Features pré-jogo (sem vazamento)

`src/features/prematch.py` constrói features usando **apenas partidas anteriores
ao kickoff** (forma, xG/xGA móveis, descanso). Um teste anti-vazamento
(`tests/test_features.py`) falha se adulterar o resultado da própria partida
mudar as suas features.

```python
from src.features import build_for_season
build_for_season(session, season_id=1)   # popula prematch_features
```

---

## Exemplos de análise

A camada `src/analysis/football.py` retorna `pandas.DataFrame`, então pode ser
usada direto em notebooks:

```python
from src.database import get_engine, session_scope
from src.analysis import football as fb

with session_scope(get_engine()) as s:
    tabela   = fb.xg_table(s, league="EPL", season="2023")
    ataque   = fb.team_xg_ranking(s, league="EPL", season="2023")
    defesa   = fb.team_xga_ranking(s, league="EPL", season="2023")
    saldo    = fb.team_xg_diff(s, league="EPL", season="2023")
    over     = fb.player_overperformers(s, league="EPL", season="2023")
    under    = fb.player_underperformers(s, league="EPL", season="2023")
    forma    = fb.recent_form(s, team="Arsenal", season="2023", n=5)
    real_exp = fb.real_vs_expected(s, league="EPL", season="2023")
```

Análises disponíveis: ranking de times por xG e por xGA, saldo xG − xGA,
jogadores com maior xG e maior xA, over/under-performance (gols − xG), forma
recente nos últimos N jogos e comparação resultado real × esperado (pts × xPTS,
gols × xG).

---

## Como adicionar novos coletores

A arquitetura foi pensada para crescer sem reescrever nada:

1. **Novo coletor**: crie `src/collectors/<fonte>_collector.py` herdando de
   `BaseCollector` (ganha cache, persistência de raw e rate limit de graça).
   Implemente `source_name` e os métodos `fetch_*`.
2. **Novo transformer**: crie `src/transformers/<fonte>_transformer.py` que
   converte o raw da fonte para os **mesmos DTOs** (`MatchDTO`, `TeamSeasonDTO`,
   etc.). O schema não muda.
3. **Reuso do repositório**: os `upsert_*` em `services/football_repository.py`
   já são idempotentes e agnósticos de fonte (deduplicam por `external_id` +
   `source_id`).
4. **Registre a fonte** em `data_sources` (o seed cobre `understat`).

Para **tênis**, o caminho é o mesmo: as tabelas já existem em
`src/models/tennis.py`; basta criar coletor + transformer + serviço de ingestão
específicos.

---

## Limitações das fontes gratuitas

- **Understat** cobre apenas 6 ligas europeias (EPL, La Liga, Bundesliga,
  Serie A, Ligue 1, RFPL), desde 2014/15. Sem copas, sem outras ligas.
- O modelo de xG é o **próprio** do Understat; xG de fontes diferentes (FBref,
  Opta) **não** é diretamente comparável. Por isso `data_sources` rastreia a
  origem de cada linha.
- Dados agregados de jogador são por temporada; o detalhamento por partida exige
  a ingestão profunda (`--with-shots`), mais custosa.
- Disponibilidade e formato dependem do site de origem e podem mudar sem aviso —
  o transformer é defensivo (campo inválido vira `None` em vez de quebrar).

---

## Cuidado com scraping e termos de uso

- Este projeto **não** faz scraping pesado de FBref, SofaScore, FotMob,
  WhoScored, Transfermarkt etc. A única fonte ativa é o Understat, via o pacote
  `understatAPI`.
- A ingestão profunda é **opt-in** (`--with-shots`) e respeita um delay
  configurável (`UNDERSTAT_REQUEST_DELAY`, padrão 2s) entre requisições.
- Há **cache local**: o JSON bruto fica em `data/raw/` e é reutilizado em vez de
  refazer a requisição (use `--no-cache` para forçar atualização).
- Respeite os **termos de uso** e o `robots.txt` da fonte. Use os dados para fins
  pessoais/analíticos/educacionais, não os redistribua sem permissão e não gere
  carga abusiva no servidor de origem.

---

## Testes

```bash
pytest            # roda toda a suíte (sem rede — usa um coletor fake)
```

Cobrem: conexão com o banco, criação das tabelas, transformação dos dados do
Understat, inserção de partidas (ingestão ponta-a-ponta) e consultas agregadas.

---

## Roadmap

- [x] Coletor de tênis (dataset Jeff Sackmann) populando o schema
- [x] Migrations com Alembic
- [x] Suporte a PostgreSQL (basta trocar `DATABASE_URL`)
- [x] Validação de qualidade de dados (`python main.py validate`)
- [x] Camada de apostas: odds time-series, mercados, predições versionadas,
      apostas simuladas, bankroll e auditoria de decisões
- [x] Features pré-jogo sem vazamento + teste anti-vazamento
- [x] Dedupe de times via aliases (IDs estáveis)
- [x] Motor de backtest + calibração (por liga/mercado/faixa de odd)
- [x] Ingestão de odds/predições/resultados via JSON + comandos de CLI
- [ ] Coletor próprio de odds em tempo real (hoje recebidas de sistema externo)
- [ ] Mais coletores de futebol mapeando para os mesmos DTOs
