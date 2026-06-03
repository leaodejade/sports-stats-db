"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from ..database.base import Base
from . import betting, context, features, football, ingest, tennis  # noqa: F401  (import for side effect: table registration)
from .context import FundamentalNote, MatchContext
from .ingest import OddsIngestRaw
from .betting import (
    BankrollTransaction,
    BetDecision,
    Bookmaker,
    CurrentOdds,
    Market,
    MarketResult,
    OddsSnapshot,
    Prediction,
    SimulatedBet,
)
from .features import PrematchFeature
from .football import (
    Competition,
    Country,
    DataSource,
    IngestionLog,
    Match,
    MatchPlayerStat,
    MatchTeamStat,
    Player,
    PlayerSeasonStat,
    Season,
    Shot,
    Sport,
    Standing,
    Team,
    TeamAlias,
)
from .tennis import (
    TennisMatch,
    TennisMatchStat,
    TennisPlayer,
    TennisRanking,
    TennisSurface,
    TennisTournament,
)

__all__ = [
    "Base",
    # football
    "Sport",
    "Country",
    "DataSource",
    "Competition",
    "Season",
    "Team",
    "TeamAlias",
    "Player",
    "Match",
    "MatchTeamStat",
    "MatchPlayerStat",
    "Shot",
    "Standing",
    "PlayerSeasonStat",
    "IngestionLog",
    # tennis
    "TennisSurface",
    "TennisPlayer",
    "TennisTournament",
    "TennisMatch",
    "TennisMatchStat",
    "TennisRanking",
    # betting
    "Bookmaker",
    "Market",
    "OddsSnapshot",
    "CurrentOdds",
    "MarketResult",
    "Prediction",
    "SimulatedBet",
    "BankrollTransaction",
    "BetDecision",
    # features
    "PrematchFeature",
    # context
    "MatchContext",
    "FundamentalNote",
    # ingestion staging
    "OddsIngestRaw",
]
