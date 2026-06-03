"""Write API + idempotent upserts for the betting data layer.

This is what an external odds-scraper / model calls to persist its output. Like
``football_repository``, every write looks an entity up by its natural key and
updates-or-inserts, so re-running never duplicates rows.

Typical flow from the external system::

    with session_scope(engine) as s:
        match_id = resolve_match(s, "Arsenal", "Chelsea", "EPL", "2023")
        record_odds(s, match_id, OddsDTO(bookmaker="Pinnacle", market="1x2",
                                         selection="home", odd=2.10, is_closing=True))
        record_prediction(s, match_id, PredictionDTO(model_name="poisson",
                          model_version="1.3", market="1x2", selection="home",
                          probability=0.52))
        bet = place_bet(s, match_id, BetDTO(market="1x2", selection="home",
                        odd_taken=2.10, stake=1.0, bookmaker="Pinnacle"))
        settle_bet(s, bet.id, "won")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    BankrollTransaction,
    Bookmaker,
    CurrentOdds,
    Market,
    MarketResult,
    Match,
    OddsSnapshot,
    Prediction,
    Season,
    SimulatedBet,
)
from ..transformers import BetDTO, MarketResultDTO, OddsDTO, PredictionDTO
from . import reference_service as ref
from . import football_repository as fb_repo


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _implied(odd: Optional[float]) -> Optional[float]:
    """Decimal odd -> implied probability (no de-vig)."""
    if odd is None or odd <= 0:
        return None
    return 1.0 / odd


def _line_match(column, line: Optional[float]):
    """Equality predicate that also matches ``NULL`` lines correctly."""
    return column.is_(None) if line is None else column == line


# ---------------------------------------------------------------------------
# Reference get-or-create
# ---------------------------------------------------------------------------
def get_or_create_bookmaker(
    session: Session,
    name: str,
    slug: Optional[str] = None,
    country: Optional[str] = None,
    is_exchange: bool = False,
) -> Bookmaker:
    bk = session.scalar(select(Bookmaker).where(Bookmaker.name == name))
    if bk is None:
        bk = Bookmaker(
            name=name,
            slug=slug or name.lower().replace(" ", "_"),
            country=country,
            is_exchange=is_exchange,
        )
        session.add(bk)
        session.flush()
    return bk


def get_or_create_market(
    session: Session,
    code: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Market:
    market = session.scalar(select(Market).where(Market.code == code))
    if market is None:
        market = Market(code=code, name=name or code.upper(), description=description)
        session.add(market)
        session.flush()
    return market


# ---------------------------------------------------------------------------
# Match resolution (for callers that only know names)
# ---------------------------------------------------------------------------
def resolve_match(
    session: Session,
    home: str,
    away: str,
    league_code: str,
    season: str,
    kickoff: Optional[datetime] = None,
    source_name: str = "manual",
) -> int:
    """Return the ``matches.id`` for a fixture, creating teams/match if needed.

    Dedupes on (season, home_team, away_team) so the same fixture maps to one
    row even without a source-specific external id.
    """
    sport = ref.get_or_create_sport(session, "Football")
    source = ref.get_or_create_source(session, source_name)
    competition = ref.get_or_create_competition(session, sport, source, league_code)
    season_obj = ref.get_or_create_season(session, competition, season)

    home_team = fb_repo.get_or_create_team(session, sport, source, None, home)
    away_team = fb_repo.get_or_create_team(session, sport, source, None, away)

    match = session.scalar(
        select(Match).where(
            Match.season_id == season_obj.id,
            Match.home_team_id == home_team.id,
            Match.away_team_id == away_team.id,
        )
    )
    if match is None:
        match = Match(
            competition_id=competition.id,
            season_id=season_obj.id,
            source_id=source.id,
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            match_datetime=kickoff,
        )
        session.add(match)
        session.flush()
    elif kickoff is not None and match.match_datetime is None:
        match.match_datetime = kickoff
    return match.id


# ---------------------------------------------------------------------------
# Odds
# ---------------------------------------------------------------------------
def record_odds(
    session: Session,
    match_id: int,
    dto: OddsDTO,
    source_id: Optional[int] = None,
) -> OddsSnapshot:
    """Append an ``OddsSnapshot`` and upsert the matching ``CurrentOdds`` row."""
    bookmaker = get_or_create_bookmaker(session, dto.bookmaker)
    market = get_or_create_market(session, dto.market)
    captured = dto.captured_at or _utcnow()
    implied = _implied(dto.odd)

    snapshot = OddsSnapshot(
        match_id=match_id,
        bookmaker_id=bookmaker.id,
        market_id=market.id,
        source_id=source_id,
        selection=dto.selection,
        line=dto.line,
        odd=dto.odd,
        implied_prob=implied,
        is_opening=dto.is_opening,
        is_closing=dto.is_closing,
        captured_at=captured,
        source_url=dto.source_url,
    )
    session.add(snapshot)

    current = session.scalar(
        select(CurrentOdds).where(
            CurrentOdds.match_id == match_id,
            CurrentOdds.bookmaker_id == bookmaker.id,
            CurrentOdds.market_id == market.id,
            CurrentOdds.selection == dto.selection,
            _line_match(CurrentOdds.line, dto.line),
        )
    )
    # Only overwrite the "current" price with a newer capture.
    if current is None:
        current = CurrentOdds(
            match_id=match_id,
            bookmaker_id=bookmaker.id,
            market_id=market.id,
            selection=dto.selection,
            line=dto.line,
        )
        session.add(current)
    if current.captured_at is None or captured >= current.captured_at:
        current.odd = dto.odd
        current.implied_prob = implied
        current.captured_at = captured

    session.flush()
    return snapshot


def record_odds_bulk(
    session: Session,
    match_id: int,
    dtos: list[OddsDTO],
    source_id: Optional[int] = None,
) -> int:
    for dto in dtos:
        record_odds(session, match_id, dto, source_id=source_id)
    return len(dtos)


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------
def record_prediction(
    session: Session,
    match_id: int,
    dto: PredictionDTO,
) -> Prediction:
    market = get_or_create_market(session, dto.market)
    fair = 1.0 / dto.probability if dto.probability and dto.probability > 0 else None

    row = session.scalar(
        select(Prediction).where(
            Prediction.match_id == match_id,
            Prediction.model_name == dto.model_name,
            Prediction.model_version == dto.model_version,
            Prediction.market_id == market.id,
            Prediction.selection == dto.selection,
            _line_match(Prediction.line, dto.line),
        )
    )
    if row is None:
        row = Prediction(
            match_id=match_id,
            model_name=dto.model_name,
            model_version=dto.model_version,
            market_id=market.id,
            selection=dto.selection,
            line=dto.line,
        )
        session.add(row)

    row.probability = dto.probability
    row.fair_odd = fair
    row.predicted_at = dto.predicted_at or _utcnow()
    row.extra = dto.extra
    # Edge vs the best stored price for this selection, if any.
    best = _best_current_odd(session, match_id, market.id, dto.selection, dto.line)
    row.edge = (dto.probability * best - 1.0) if best else None
    session.flush()
    return row


def _best_current_odd(
    session: Session, match_id: int, market_id: int, selection: str, line: Optional[float]
) -> Optional[float]:
    return session.scalar(
        select(func.max(CurrentOdds.odd)).where(
            CurrentOdds.match_id == match_id,
            CurrentOdds.market_id == market_id,
            CurrentOdds.selection == selection,
            _line_match(CurrentOdds.line, line),
        )
    )


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
def upsert_market_result(
    session: Session,
    match_id: int,
    dto: MarketResultDTO,
) -> MarketResult:
    market = get_or_create_market(session, dto.market)
    row = session.scalar(
        select(MarketResult).where(
            MarketResult.match_id == match_id,
            MarketResult.market_id == market.id,
            MarketResult.selection == dto.selection,
            _line_match(MarketResult.line, dto.line),
        )
    )
    if row is None:
        row = MarketResult(
            match_id=match_id,
            market_id=market.id,
            selection=dto.selection,
            line=dto.line,
        )
        session.add(row)
    row.outcome = dto.outcome
    row.result_value = dto.result_value
    row.settled_at = dto.settled_at or _utcnow()
    session.flush()
    return row


# ---------------------------------------------------------------------------
# Bankroll + simulated bets
# ---------------------------------------------------------------------------
def current_balance(session: Session) -> float:
    """Running bankroll balance = sum of all signed transaction amounts."""
    total = session.scalar(select(func.coalesce(func.sum(BankrollTransaction.amount), 0.0)))
    return float(total or 0.0)


def _add_transaction(
    session: Session,
    kind: str,
    amount: float,
    ts: datetime,
    bet_id: Optional[int] = None,
    note: Optional[str] = None,
) -> BankrollTransaction:
    balance_after = current_balance(session) + amount
    txn = BankrollTransaction(
        ts=ts, kind=kind, amount=amount, balance_after=balance_after,
        bet_id=bet_id, note=note,
    )
    session.add(txn)
    session.flush()
    return txn


def deposit(session: Session, amount: float, ts: Optional[datetime] = None) -> BankrollTransaction:
    return _add_transaction(session, "deposit", abs(amount), ts or _utcnow(), note="deposit")


def place_bet(
    session: Session,
    match_id: int,
    dto: BetDTO,
) -> SimulatedBet:
    """Record a pending paper bet and debit the bankroll by the stake."""
    market = get_or_create_market(session, dto.market)
    bookmaker_id = None
    if dto.bookmaker:
        bookmaker_id = get_or_create_bookmaker(session, dto.bookmaker).id
    placed = dto.placed_at or _utcnow()

    bet = SimulatedBet(
        match_id=match_id,
        bookmaker_id=bookmaker_id,
        market_id=market.id,
        prediction_id=dto.prediction_id,
        selection=dto.selection,
        line=dto.line,
        odd_taken=dto.odd_taken,
        stake=dto.stake,
        status="pending",
        placed_at=placed,
        model_name=dto.model_name,
        model_version=dto.model_version,
    )
    session.add(bet)
    session.flush()

    _add_transaction(session, "stake", -dto.stake, placed, bet_id=bet.id,
                     note=f"stake bet#{bet.id}")
    return bet


def settle_bet(
    session: Session,
    bet_id: int,
    outcome: str,
    settled_at: Optional[datetime] = None,
) -> SimulatedBet:
    """Settle a pending bet and credit any return to the bankroll.

    ``outcome``: ``won`` | ``lost`` | ``push`` | ``void`` | ``cashout``.
    PnL is net of stake; the bankroll receives the gross return.
    """
    bet = session.get(SimulatedBet, bet_id)
    if bet is None:
        raise ValueError(f"SimulatedBet {bet_id} not found")
    if bet.status != "pending":
        raise ValueError(f"Bet {bet_id} already settled ({bet.status})")

    when = settled_at or _utcnow()
    if outcome == "won":
        gross_return = bet.stake * bet.odd_taken
        pnl = bet.stake * (bet.odd_taken - 1.0)
    elif outcome == "lost":
        gross_return = 0.0
        pnl = -bet.stake
    elif outcome in ("push", "void"):
        gross_return = bet.stake
        pnl = 0.0
    else:
        raise ValueError(f"Unsupported outcome: {outcome!r}")

    bet.status = outcome
    bet.settled_at = when
    bet.pnl = round(pnl, 6)
    session.flush()

    if gross_return:
        _add_transaction(session, "return", gross_return, when, bet_id=bet.id,
                         note=f"return bet#{bet.id} ({outcome})")
    return bet


# ---------------------------------------------------------------------------
# Maintenance: deterministic closing line
# ---------------------------------------------------------------------------
def mark_closing_odds(session: Session, match_id: Optional[int] = None) -> int:
    """Flag the closing snapshot deterministically per selection/bookmaker.

    The closing price is the LAST snapshot captured at/before kickoff for each
    (bookmaker, market, selection, line). Everything else is set non-closing, so
    ``is_closing`` no longer depends on whoever wrote the row. Returns the number
    of snapshots marked closing.
    """
    stmt = select(Match).where(Match.match_datetime.is_not(None))
    if match_id is not None:
        stmt = stmt.where(Match.id == match_id)
    matches = session.scalars(stmt).all()

    marked = 0
    for match in matches:
        snaps = session.scalars(
            select(OddsSnapshot).where(OddsSnapshot.match_id == match.id)
        ).all()
        for s in snaps:
            s.is_closing = False
        best: dict[tuple, OddsSnapshot] = {}
        for s in snaps:
            if s.captured_at is None or s.captured_at > match.match_datetime:
                continue
            key = (s.bookmaker_id, s.market_id, s.selection, s.line)
            cur = best.get(key)
            if cur is None or s.captured_at > cur.captured_at:
                best[key] = s
        for s in best.values():
            s.is_closing = True
            marked += 1
    session.flush()
    return marked
