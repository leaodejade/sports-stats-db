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

Tênis (futuro): `tennis_surfaces`, `tennis_players`, `tennis_tournaments`,
`tennis_matches`, `tennis_match_stats`, `tennis_rankings`.

> Nota de design: `player_season_stats` e `standings` guardam agregados de
> temporada (1 requisição por liga/temporada cada). `match_player_stats` e
> `shots` só são preenchidos na ingestão profunda (`--with-shots`), que custa
> ~2 requisições por partida.

---

## Instalação

Requisitos: **Python 3.11+**.

```bash
cd sports-stats-db

python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env   # Windows: copy .env.example .env
```

Ajuste `.env` se quiser (caminho do banco, nível de log, delay de requisições).
Os defaults já funcionam com SQLite em `data/processed/sports.db`.

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

- [ ] Coletor de tênis (ex.: dataset Jeff Sackmann) populando o schema dormente
- [ ] Migrations com Alembic (hoje o schema é criado via `create_all`)
- [ ] Suporte a PostgreSQL (basta trocar `DATABASE_URL`)
- [ ] Mais coletores de futebol mapeando para os mesmos DTOs
