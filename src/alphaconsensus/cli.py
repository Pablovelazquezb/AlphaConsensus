"""Command line interface.

    python -m alphaconsensus demo            # pipeline completo con datos sintéticos
    python -m alphaconsensus ingest --source apify --handle demo_semis
    python -m alphaconsensus accounts        # inspeccionar la whitelist
    python -m alphaconsensus paper           # verificar credenciales de Alpaca paper
    python -m alphaconsensus congress        # divulgaciones del Congreso (STOCK Act)
    python -m alphaconsensus house           # histórico oficial de la Cámara (PTR PDFs)
    python -m alphaconsensus congress-score  # credibilidad desde la fecha de divulgación
    python -m alphaconsensus x-history       # 12-24 meses de tuits → pesos de credibilidad
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from . import __version__
from .backtest.runner import RunResult, run_demo
from .config import Settings, load_dotenv, load_settings
from .ingestion.apify import ApifyError, ApifySource
from .ingestion.mock import DEMO_SKILLS
from .ingestion.pipeline import TweetFilter
from .ingestion.x_api import XApiSource
from .models import TradingSignal
from .nlp.service import SignalExtractor
from .storage.db import Repository

LINE = "─" * 78


def _header(title: str) -> None:
    print(f"\n{title}\n{LINE}")


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _pct(value: float, signed: bool = True) -> str:
    return f"{value * 100:+.2f}%" if signed else f"{value * 100:.2f}%"


def _qty(value: float) -> str:
    return f"{round(float(value), 4):g}"


def _safe_ratio(value: float) -> str:
    if value == float("inf"):
        return "∞"
    return f"{value:.2f}"


def _print_accounts(result: RunResult) -> None:
    _header("Credibilidad (historial sintético)  *skill = verdad oculta del generador")
    print(f"{'handle':<18}{'calls':>7}{'hit%':>8}{'exceso':>9}{'peso':>7}{'skill*':>8}  estado")
    ordered = sorted(result.scores.values(), key=lambda s: (-s.weight, -s.n_calls))
    for score in ordered[:30]:
        status = "provisional" if score.provisional else ("activa" if score.weight > 0 else "sin peso")
        skill = DEMO_SKILLS.get(score.handle, 0.0)
        print(
            f"{score.handle:<18}{score.n_calls:>7}{score.hit_rate * 100:>7.1f}%"
            f"{_pct(score.mean_excess_return):>9}{score.weight:>7.2f}{skill:>8.2f}  {status}"
        )


def _print_consensus(result: RunResult) -> None:
    _header("Señales de consenso")
    if not result.consensus:
        print("  ninguna: el quórum no se alcanzó en la ventana simulada.")
        return
    print(f"{'fecha':<12}{'ticker':<8}{'lado':<7}{'peso':>6}{'cuentas':>8}{'horiz.':>7}  autores")
    for signal in result.consensus[:20]:
        print(
            f"{signal.created_at.date().isoformat():<12}{signal.ticker:<8}{signal.side:<7}"
            f"{signal.score:>6.2f}{signal.n_accounts:>8}{signal.horizon_days:>6}d  "
            f"{', '.join(signal.accounts[:4])}"
        )
    if len(result.consensus) > 20:
        print(f"  … {len(result.consensus) - 20} más")


def _print_trades(result: RunResult) -> None:
    _header("Operaciones ejecutadas")
    if not result.trades:
        print("  ninguna.")
        return
    print(f"{'ticker':<8}{'lado':<7}{'qty':>6}{'entrada':>10}{'salida':>10}{'pnl':>11}{'%':>9}  motivo")
    for trade in result.trades:
        print(
            f"{trade.ticker:<8}{trade.side:<7}{_qty(trade.qty):>6}{trade.entry_price:>10.2f}"
            f"{(trade.exit_price or 0):>10.2f}{trade.pnl:>11.2f}{_pct(trade.return_pct):>9}"
            f"  {trade.exit_reason}"
        )


def _print_report(result: RunResult, settings: Settings) -> None:
    stats = result.stats
    print("\n" + "═" * 78)
    print(" AlphaConsensus · demo end-to-end (datos sintéticos)")
    print("═" * 78)
    print(
        f"Periodo live : {result.live_start.date()} → {result.live_end.date()} "
        f"({len(result.market.trading_days)} sesiones en total)"
    )
    print(f"Universo     : {len(settings.universe)} tickers | whitelist: {len(settings.accounts)} cuentas")
    print(f"Seed         : {result.seed}")

    _header("Pipeline")
    ingest = result.ingest_stats
    print(f"  tweets generados       {ingest.get('seen', 0):>7,}")
    print(f"  aceptados              {ingest.get('accepted', 0):>7,}")
    print(
        f"  descartados            {ingest.get('seen', 0) - ingest.get('accepted', 0):>7,}"
        f"  (rt {ingest.get('retweet', 0)}, replies {ingest.get('reply', 0)},"
        f" cortos {ingest.get('too_short', 0)}, spam {ingest.get('promo', 0)})"
    )
    print(f"  señales accionables    {stats['actionable_signals']:>7,}")
    print(f"  latencia NLP           p50 {result.parse_latency_ms['p50']:.2f} ms · "
          f"p95 {result.parse_latency_ms['p95']:.2f} ms")

    _print_accounts(result)
    _print_consensus(result)

    _header("Riesgo y ejecución")
    if result.outcome.rejections:
        detail = ", ".join(
            f"{k}={v}" for k, v in sorted(result.outcome.rejections.items(), key=lambda kv: -kv[1])
        )
        print(f"  rechazos: {detail}")
    print(f"  señales de consenso    {stats['consensus_signals']:>7,}")
    print(f"  ejecutadas             {stats['executed_signals']:>7,}")

    _header("Resultados (paper)")
    print(f"  capital inicial        {_money(stats['starting_equity'])}")
    print(f"  equity final           {_money(stats['final_equity'])}  ({_pct(stats['total_return'])})")
    print(f"  benchmark SPY          {_pct(stats['benchmark_return'])}  →  exceso {_pct(stats['excess_vs_benchmark'])}")
    print(
        f"  trades                 {stats['trades']:>3} | win rate {_pct(stats['win_rate'], signed=False)}"
        f" | profit factor {_safe_ratio(stats['profit_factor'])}"
    )
    print(
        f"  max drawdown           {_pct(stats['max_drawdown'])} | Sharpe {stats['sharpe']:.2f}"
        f" | hold medio {stats['avg_hold_days']:.1f} días"
    )
    print(f"  P&L realizado          {_money(stats['total_pnl'])}")

    _header("Ablación: ¿aporta algo la capa de credibilidad?")
    equal = result.benchmark.stats
    print(f"  {'variante':<16}{'señales':>9}{'trades':>8}{'ret/trade':>11}{'win%':>8}")
    print(
        f"  con pesos       {stats['consensus_signals']:>9}{stats['trades']:>8}"
        f"{_pct(stats['avg_trade_pct']):>11}{_pct(stats['win_rate'], signed=False):>8}"
    )
    print(
        f"  pesos iguales   {equal['consensus_signals']:>9}{equal['trades']:>8}"
        f"{_pct(equal['avg_trade_pct']):>11}{_pct(equal['win_rate'], signed=False):>8}"
    )
    print(
        "  misma estrategia y umbrales; la variante igualada dispara más señales (incluye ruido)."
        "\n  El retorno total no es comparable: el capital desplegado es distinto, por eso se"
        "\n  compara el retorno medio por operación. Un solo seed no es evidencia: usa"
        "\n  `python -m alphaconsensus robustness --seeds 20`."
    )

    _print_trades(result)
    print(
        "\n⚠️  Datos 100% sintéticos: las cuentas 'buenas' conocen el futuro por construcción."
        "\n    Este demo valida el pipeline, NO la estrategia ni la credibilidad de nadie."
    )
    print("═" * 78)


def cmd_demo(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = run_demo(settings, seed=args.seed, persist=not args.no_db, db_path=args.db)
    if args.json:
        print(json.dumps(result.to_report(), indent=2, ensure_ascii=False))
    else:
        _print_report(result, settings)
    return 0


def _parse_day(value: Optional[str], default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.replace(tzinfo=timezone.utc)


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = load_settings()
    handles = [args.handle.lstrip("@").lower()] if args.handle else settings.enabled_handles
    if not handles:
        print("Whitelist vacía: revisa config/accounts.json", file=sys.stderr)
        return 2

    until = _parse_day(args.until, datetime.now(timezone.utc))
    since = _parse_day(args.since, until - timedelta(days=7))

    if args.source == "apify":
        source = ApifySource()
        if not source.available:
            print("Falta APIFY_TOKEN. Copia .env.example a .env y añade tu token.", file=sys.stderr)
            return 2
    elif args.source == "x":
        source = XApiSource()
        if not source.available:
            print("Falta X_BEARER_TOKEN. Copia .env.example a .env y añade tu token.", file=sys.stderr)
            return 2
    else:  # pragma: no cover - argparse guards this
        print(f"Fuente desconocida: {args.source}", file=sys.stderr)
        return 2

    print(f"Descargando {len(handles)} cuentas desde {source.name} ({since.date()} → {until.date()})…")
    try:
        tweets = source.fetch(handles, since, until, limit_per_account=args.limit)
    except (ApifyError, RuntimeError) as exc:
        print(f"Error de ingesta: {exc}", file=sys.stderr)
        return 1

    tweet_filter = TweetFilter(settings.filters)
    accepted = tweet_filter.apply(tweets)
    extractor = SignalExtractor(settings)
    signals: List[TradingSignal] = []
    for tweet in accepted:
        signals.extend(extractor.parse(tweet))
    actionable = [s for s in signals if s.actionable]

    print(f"tweets descargados: {len(tweets)} | aceptados: {len(accepted)} | señales: {len(actionable)}")
    if actionable:
        print(f"\n{'ticker':<8}{'lado':<9}{'conf':>6}{'horiz.':>7}  autor               tweet")
        for signal in actionable[:30]:
            excerpt = next((t.text for t in accepted if t.id == signal.tweet_id), "")
            print(
                f"{signal.ticker:<8}{signal.direction.value:<9}{signal.confidence:>6.2f}"
                f"{signal.horizon_days:>6}d  @{signal.author:<18} {excerpt[:60]}"
            )

    repo = Repository(args.db)
    for tweet in accepted:
        repo.save_tweet(tweet)
    for signal in signals:
        repo.save_signal(signal)
    repo.commit()
    repo.close()
    print(f"\nGuardado en {args.db}")
    return 0


def cmd_accounts(args: argparse.Namespace) -> int:
    settings = load_settings()
    print(f"{'handle':<18}{'cluster':<12}{'categoría':<18}nota")
    for account in settings.accounts:
        flag = "" if account.enabled else "  [deshabilitada]"
        print(f"{account.handle:<18}{account.cluster:<12}{account.category:<18}{account.note}{flag}")
    print(f"\n{len(settings.accounts)} cuentas · {len(settings.enabled_handles)} activas")
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    """Read-only check of the Alpaca paper account. Never submits orders."""
    from .execution.alpaca import AlpacaError, AlpacaPaperBroker

    broker = AlpacaPaperBroker()
    if not broker.available:
        print(
            "Faltan ALPACA_API_KEY / ALPACA_SECRET_KEY.\n"
            "En app.alpaca.markets: Paper Trading → API Keys → Generate New Key,\n"
            "y guárdalas en .env (nunca las pegues en el chat).",
            file=sys.stderr,
        )
        return 2
    try:
        account = broker.get_account()
        positions = [] if args.no_positions else broker.get_positions()
    except AlpacaError as exc:
        print(f"Error de conexión con Alpaca: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"account": account, "positions": positions}, indent=2, ensure_ascii=False))
        return 0

    print("\nAlpaca paper — verificación de conexión (solo lectura)")
    print(LINE)
    print(f"  estado        {account.get('status', '?')}")
    print(f"  equity        {_money(float(account.get('equity', 0) or 0))}")
    print(f"  cash          {_money(float(account.get('cash', 0) or 0))}")
    print(f"  buying power  {_money(float(account.get('buying_power', 0) or 0))}")
    print(f"  moneda        {account.get('currency', '?')}")
    print(f"  endpoint      {broker.base_url}")
    print(f"\nPosiciones abiertas: {len(positions)}")
    for position in positions:
        print(
            f"  {position.get('symbol', '?'):<8} qty {position.get('qty', '?'):>8}"
            f"  entrada {position.get('avg_entry_price', '?'):>10}"
            f"  valor {position.get('market_value', '?'):>12}"
            f"  P&L {position.get('unrealized_pl', '?'):>10}"
        )

    if args.smoke_test:
        from .execution.smoke import run_smoke_test

        print("\nSmoke test: compra ~$1 de SPY, espera el fill y cierra")
        print(LINE)
        result = run_smoke_test(broker)
        if args.json:
            print(json.dumps(result.__dict__, indent=2, ensure_ascii=False, default=str))
            return 0 if result.ok else 1
        print(f"  resultado     {'OK' if result.ok else 'FALLO'}")
        if result.order_id:
            print(f"  orden         {result.order_id} ({result.status})")
        if result.qty:
            print(f"  fill          {_qty(result.qty)} @ {result.fill_price:.2f}")
        print(f"  cierre        {'sí' if result.closed else 'no'}")
        if result.closed:
            print(f"  P&L           {_money(result.pnl)}")
        print(f"  detalle       {result.message}")
        return 0 if result.ok else 1
    return 0



def cmd_congress(args: argparse.Namespace) -> int:
    """Congressional disclosures (STOCK Act) via Bargo's free API."""
    from dataclasses import asdict
    from statistics import median

    from .ingestion.congress import CongressError, CongressSource

    source = CongressSource()
    if args.health:
        try:
            print(json.dumps(source.health(), indent=2, ensure_ascii=False))
        except CongressError as exc:
            print(f"Error consultando Bargo: {exc}", file=sys.stderr)
            return 1
        return 0

    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=args.days)
    try:
        trades = source.trades(
            member=args.member,
            ticker=args.ticker,
            chamber=args.chamber,
            trade_type=args.type,
            since=since,
            until=until,
            limit=args.limit,
        )
    except CongressError as exc:
        print(f"Error consultando Bargo: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([asdict(t) for t in trades], indent=2, ensure_ascii=False, default=str))
        return 0

    if not trades:
        print(f"Sin divulgaciones entre {since} y {until} con esos filtros.")
        print("La API gratuita cubre ~3 meses; verifica el filtro o usa --health.")
        return 0

    print(f"\nDivulgaciones del Congreso · {since} → {until} · {len(trades)} operaciones")
    print(LINE)
    print(
        f"{'fecha':<12}{'divulg.':<12}{'lag':>4}  {'miembro':<26}{'ticker':<7}"
        f"{'tipo':<10}{'monto':<28}{'perf*':>8}"
    )
    for trade in trades:
        lag = f"{trade.lag_days}d" if trade.lag_days is not None else "?"
        perf = f"{trade.perf_pct:+.1f}%" if trade.perf_pct is not None else "—"
        print(
            f"{trade.transaction_date.isoformat() if trade.transaction_date else '?':<12}"
            f"{trade.disclosure_date.isoformat() if trade.disclosure_date else '?':<12}"
            f"{lag:>4}  {trade.member[:25]:<26}{trade.ticker:<7}{trade.type:<10}"
            f"{trade.amount_range[:27]:<28}{perf:>8}"
        )

    lags = [t.lag_days for t in trades if t.lag_days is not None]
    buys = sum(1 for t in trades if t.type == "purchase")
    sells = sum(1 for t in trades if t.type == "sale")
    print(LINE)
    print(f"  compras {buys} · ventas {sells} · lag mediano {median(lags):.0f} días" if lags else f"  compras {buys} · ventas {sells}")
    print("  * perf desde la transacción, no desde la divulgación: no es lo que habrías capturado.")
    print("  Ventana gratuita ~3 meses. Para backtest de 12-24 meses hace falta histórico de pago.")
    return 0



def cmd_house(args: argparse.Namespace) -> int:
    """Download and parse official House PTR PDFs into a historical dataset."""
    from collections import Counter
    from pathlib import Path as _Path
    from statistics import median

    from .ingestion.house_clerk import DEFAULT_MEMBERS, HouseClerkSource, save_trades

    members = [m.strip() for m in args.members.split(",")] if args.members else list(DEFAULT_MEMBERS)
    source = HouseClerkSource()
    try:
        filings = source.filings(members, args.years)
    except Exception as exc:  # network/index failures
        print(f"No se pudo leer el índice de la Cámara: {exc}", file=sys.stderr)
        return 1
    if args.limit:
        filings = filings[: args.limit]
    print(f"PTRs encontrados: {len(filings)} ({', '.join(str(y) for y in args.years)})")
    if not filings:
        print("Nada que descargar: revisa los nombres o los años.", file=sys.stderr)
        return 1

    def progress(index: int, total: int, filing, rows: int) -> None:
        if index % 10 == 0 or index == total:
            print(f"  [{index}/{total}] {filing.member:<26} {filing.year}  {rows:>3} filas", flush=True)

    trades = source.sync(filings, progress=progress)
    out = save_trades(trades, _Path(args.out))
    if not trades:
        print("No se extrajo ninguna operación (¿PDFs escaneados?).", file=sys.stderr)
        return 1

    lags = [t.lag_days for t in trades if t.lag_days is not None]
    buys = sum(1 for t in trades if t.type == "purchase")
    sells = sum(1 for t in trades if t.type == "sale")
    tickers = Counter(t.ticker for t in trades)
    per_member = Counter(t.member for t in trades)
    print("\n" + LINE)
    print(f"Guardado      {out}")
    print(f"Operaciones   {len(trades):,} | tickers {len(tickers):,} | miembros {len(per_member):,}")
    print(
        f"Rango         {min(t.transaction_date for t in trades)} → "
        f"{max(t.transaction_date for t in trades)}"
    )
    print(f"Lag mediano   {median(lags):.0f} días" if lags else "Lag mediano   —")
    print(f"Compras/ventas {buys:,} / {sells:,}")
    print(
        f"PDFs          {source.stats['pdfs_downloaded']} descargados, "
        f"{source.stats['pdfs_cached']} en caché, {source.stats['pdfs_empty']} sin texto"
    )
    print(f"Filas sin ticker {source.stats['rows_without_ticker']:,}")
    print("Top tickers   " + ", ".join(f"{t} ({n})" for t, n in tickers.most_common(10)))
    print("Por miembro   " + ", ".join(f"{m} ({n})" for m, n in per_member.most_common(12)))
    return 0



def cmd_congress_score(args: argparse.Namespace) -> int:
    """Score congressional members using returns from the disclosure date."""
    from .credibility.alpaca_bars import AlpacaBars, AlpacaBarsError
    from .credibility.congress_scorer import CongressCredibilityScorer, CongressScorerConfig
    from .ingestion.congress import CongressTrade

    path = Path(args.input)
    if not path.exists():
        print(f"No existe {path}. Corre primero: python -m alphaconsensus house", file=sys.stderr)
        return 2
    raw = json.loads(path.read_text(encoding="utf-8"))
    trades = [CongressTrade.from_dict(row) for row in raw]
    trades = [t for t in trades if t.ticker and t.transaction_date and t.disclosure_date]
    if args.member:
        needle = args.member.lower()
        trades = [t for t in trades if needle in t.member.lower()]
    if args.min_amount:
        trades = [t for t in trades if (t.amount_high or 0) >= args.min_amount]
    if not trades:
        print("No hay operaciones que puntuar con esos filtros.", file=sys.stderr)
        return 1

    start = min(t.transaction_date for t in trades) - timedelta(days=10)
    end = datetime.now(timezone.utc).date()
    tickers = sorted({t.ticker for t in trades} | {args.benchmark})
    print(f"Barras diarias: {len(tickers)} tickers ({start} → {end})…", flush=True)
    try:
        prices = AlpacaBars().fetch(tickers, start, end)
    except AlpacaBarsError as exc:
        print(f"Error de datos: {exc}", file=sys.stderr)
        return 1

    config = CongressScorerConfig(horizon_days=args.horizon, min_trades=args.min_trades)
    scores = CongressCredibilityScorer(config).score(trades, prices, benchmark=args.benchmark)
    if not scores:
        print("Sin datos suficientes para puntuar.", file=sys.stderr)
        return 1

    ordered = sorted(scores.values(), key=lambda s: (-s.weight, -s.n_trades))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([s.to_row() for s in ordered], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if args.json:
        print(json.dumps([s.to_row() for s in ordered], indent=2, ensure_ascii=False))
        return 0

    print("\n" + LINE)
    print(
        f"{'miembro':<26}{'ops':>4}{'C/V':>8}{'hit%':>8}"
        f"{'exc.div':>9}{'exc.txn':>9}{'decay':>8}{'t':>6}{'peso':>7}  estado"
    )
    for score in ordered:
        status = "provisional" if score.provisional else ("ok" if score.weight > 0 else "sin peso")
        print(
            f"{score.member[:25]:<26}{score.n_trades:>4}{score.buys:>4}/{score.sells:<3}"
            f"{score.hit_rate_disc * 100:>7.1f}%{_pct(score.mean_excess_disc):>9}"
            f"{_pct(score.mean_excess_txn):>9}{_pct(score.decay):>8}{score.t_stat:>6.2f}"
            f"{score.weight:>7.2f}  {status}"
        )
    print(LINE)
    print(f"Guardado {out_path}")
    print("  exc.div = exceso vs SPY desde la divulgación (tradable) · exc.txn = desde la transacción (no tradable)")
    print("  decay = cuánto se pierde por el retraso legal de hasta 45 días.")
    return 0



def cmd_x_history(args: argparse.Namespace) -> int:
    """Download X timelines, extract signals and score account credibility."""
    from .config import load_x_accounts
    from .credibility.alpaca_bars import AlpacaBars, AlpacaBarsError
    from .credibility.prices import BarMarket
    from .credibility.scorer import CredibilityScorer
    from .ingestion.apify import ApifyError, ApifySource

    settings = load_settings()
    accounts = load_x_accounts(settings.root / "config" / "x_accounts.json")
    if args.handles:
        from .config import XAccount

        wanted = [h.strip().lstrip("@").lower() for h in args.handles.split(",") if h.strip()]
        known = {a.handle: a for a in accounts}
        accounts = [known.get(h, XAccount(handle=h, role="voter")) for h in wanted]
    enabled = [a for a in accounts if a.enabled]
    if not enabled:
        print("No hay cuentas de X habilitadas en config/x_accounts.json", file=sys.stderr)
        return 2

    actor = args.actor or (
        "apidojo/tweet-scraper" if args.source == "search" else "apidojo/twitter-profile-scraper"
    )
    source = ApifySource(actor=actor)
    if not source.available:
        print(
            "Falta APIFY_TOKEN en .env.\n"
            "Apify Console → Settings → Integrations → API token.",
            file=sys.stderr,
        )
        return 2

    cutoff = (
        datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        if args.since
        else datetime.now(timezone.utc) - timedelta(days=730)
    )
    until = (
        datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc)
        if args.until
        else datetime.now(timezone.utc)
    )
    mode = "búsqueda histórica" if args.source == "search" else "timelines"
    print(
        f"Descargando {len(enabled)} cuentas por {mode} "
        f"(hasta {args.limit} tuits c/u)…",
        flush=True,
    )
    try:
        if args.source == "search":
            raw = source.fetch_history(
                [a.handle for a in enabled], cutoff, until, args.limit,
                workers=args.workers,
            )
        else:
            raw = source.fetch_profiles(
                [a.handle for a in enabled], args.limit, workers=args.workers
            )
    except ApifyError as exc:
        print(f"Error de Apify: {exc}", file=sys.stderr)
        return 1
    raw = [t for t in raw if cutoff <= t.created_at <= until]
    filtered = TweetFilter(settings.filters).apply(raw)
    extractor = SignalExtractor(settings)
    signals = []
    for tweet in filtered:
        signals.extend(extractor.parse(tweet))
    actionable = [s for s in signals if s.actionable]
    print(
        f"tuits {len(raw):,} → aceptados {len(filtered):,} → señales {len(actionable):,}",
        flush=True,
    )
    if not actionable:
        print("Sin señales accionables: revisa las cuentas o el parser.", file=sys.stderr)
        return 1

    tickers = sorted({s.ticker for s in actionable} | {args.benchmark})
    start = min(s.created_at.date() for s in actionable) - timedelta(days=10)
    end = datetime.now(timezone.utc).date()
    print(f"Barras diarias: {len(tickers)} tickers…", flush=True)
    try:
        bars = AlpacaBars().fetch(tickers, start, end)
    except AlpacaBarsError as exc:
        print(f"Error de datos: {exc}", file=sys.stderr)
        return 1

    market = BarMarket(bars, benchmark=args.benchmark)
    scores = CredibilityScorer().score(actionable, market)
    roles = {a.handle: a.role for a in enabled}

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tweets.json").write_text(
        json.dumps([t.to_row() for t in filtered], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "signals.json").write_text(
        json.dumps([s.to_row() for s in signals], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    rows = []
    for handle, score in sorted(scores.items(), key=lambda kv: -kv[1].weight):
        role = roles.get(handle, "voter")
        rows.append(
            {
                **score.to_row(),
                "role": role,
                "effective_weight": 0.0 if role == "context" else score.weight,
            }
        )
    (out_dir / "x_scores.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n" + LINE)
    print(
        f"{'cuenta':<18}{'rol':<9}{'calls':>6}{'hit%':>8}{'exceso':>9}{'peso':>7}  estado"
    )
    for row in rows:
        status = "provisional" if row["provisional"] else ("ok" if row["weight"] > 0 else "sin peso")
        print(
            f"{row['handle'][:17]:<18}{row['role']:<9}{row['n_calls']:>6}"
            f"{row['hit_rate'] * 100:>7.1f}%{_pct(row['mean_excess_return']):>9}"
            f"{row['effective_weight']:>7.2f}  {status}"
        )
    print(LINE)
    print(f"Guardado en {out_dir}")
    print(f"  benchmark {args.benchmark} · peso efectivo 0 para cuentas de contexto")
    return 0


def cmd_robustness(args: argparse.Namespace) -> int:
    settings = load_settings()
    rows = []
    for seed in range(1, args.seeds + 1):
        result = run_demo(settings, seed=seed, persist=False)
        rows.append((seed, result.stats, result.benchmark.stats))
        print(
            f"  seed {seed:>3}  con pesos {_pct(result.stats['total_return']):>8}"
            f"  ret/trade {_pct(result.stats['avg_trade_pct']):>8}"
            f"  |  iguales {_pct(result.benchmark.stats['total_return']):>8}"
            f"  ret/trade {_pct(result.benchmark.stats['avg_trade_pct']):>8}",
            flush=True,
        )

    def mean(key: str, which: int) -> float:
        return sum(row[which][key] for row in rows) / len(rows)

    print("\n" + LINE)
    print(f"{'métrica':<26}{'con pesos':>12}{'pesos iguales':>16}")
    for key, label in (
        ("total_return", "retorno total medio"),
        ("avg_trade_pct", "retorno medio/trade"),
        ("win_rate", "win rate medio"),
        ("max_drawdown", "max drawdown medio"),
        ("sharpe", "sharpe medio"),
        ("consensus_signals", "señales medias"),
        ("trades", "trades medios"),
    ):
        left, right = mean(key, 1), mean(key, 2)
        if key in {"total_return", "avg_trade_pct", "win_rate", "max_drawdown"}:
            print(f"{label:<26}{_pct(left):>12}{_pct(right):>16}")
        else:
            print(f"{label:<26}{left:>12.2f}{right:>16.2f}")
    print(LINE)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alphaconsensus",
        description="Consenso ponderado de cuentas de X para paper trading (research).",
    )
    parser.add_argument("--version", action="version", version=f"alphaconsensus {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="pipeline completo con datos sintéticos")
    demo.add_argument("--seed", type=int, default=None)
    demo.add_argument("--json", action="store_true", help="imprimir el reporte en JSON")
    demo.add_argument("--no-db", action="store_true", help="no persistir en SQLite")
    demo.add_argument("--db", type=Path, default=None)
    demo.add_argument("--config", type=Path, default=None, help=argparse.SUPPRESS)
    demo.set_defaults(func=cmd_demo)

    ingest = sub.add_parser("ingest", help="descargar y parsear tweets reales")
    ingest.add_argument("--source", choices=["apify", "x"], default="apify")
    ingest.add_argument("--handle", default=None, help="una sola cuenta (por defecto: whitelist)")
    ingest.add_argument("--since", default=None, help="YYYY-MM-DD")
    ingest.add_argument("--until", default=None, help="YYYY-MM-DD")
    ingest.add_argument("--limit", type=int, default=100, help="tweets máximos por cuenta")
    ingest.add_argument("--db", type=Path, default=Path("data/alphaconsensus.db"))
    ingest.add_argument("--config", type=Path, default=None, help=argparse.SUPPRESS)
    ingest.set_defaults(func=cmd_ingest)

    accounts = sub.add_parser("accounts", help="mostrar la whitelist")
    accounts.add_argument("--config", type=Path, default=None, help=argparse.SUPPRESS)
    accounts.set_defaults(func=cmd_accounts)

    paper = sub.add_parser("paper", help="verificar la conexión con Alpaca paper (solo lectura)")
    paper.add_argument("--json", action="store_true")
    paper.add_argument(
        "--smoke-test",
        action="store_true",
        help="compra ~$1 de SPY y la cierra para validar la ruta de órdenes",
    )
    paper.add_argument("--no-positions", action="store_true", help=argparse.SUPPRESS)
    paper.set_defaults(func=cmd_paper)

    xhist = sub.add_parser(
        "x-history", help="histórico de tuits por timeline y pesos de credibilidad"
    )
    xhist.add_argument("--since", default=None, help="YYYY-MM-DD (por defecto: 2 años)")
    xhist.add_argument("--until", default=None, help="YYYY-MM-DD (por defecto: hoy)")
    xhist.add_argument(
        "--source", choices=["timeline", "search"], default="timeline",
        help="timeline = recientes; search = histórico por fechas",
    )
    xhist.add_argument("--limit", type=int, default=800, help="tuits por cuenta")
    xhist.add_argument("--benchmark", default="SPY", help="SPY, QQQ, etc.")
    xhist.add_argument("--handles", default=None, help="lista separada por comas")
    xhist.add_argument("--workers", type=int, default=4, help="descargas en paralelo")
    xhist.add_argument("--actor", default=None, help="actor de Apify (opcional)")
    xhist.add_argument("--out-dir", type=Path, default=Path("data/x"))
    xhist.set_defaults(func=cmd_x_history)

    score = sub.add_parser(
        "congress-score", help="credibilidad del Congreso medida desde la divulgación"
    )
    score.add_argument("--input", type=Path, default=Path("data/congress/house_trades.json"))
    score.add_argument("--horizon", type=int, default=21, help="días de tenencia")
    score.add_argument("--min-trades", type=int, default=8)
    score.add_argument("--min-amount", type=float, default=0.0)
    score.add_argument("--benchmark", default="SPY", help="SPY, QQQ o el ETF sectorial")
    score.add_argument("--member", default=None)
    score.add_argument("--out", type=Path, default=Path("data/congress/congress_scores.json"))
    score.add_argument("--json", action="store_true")
    score.set_defaults(func=cmd_congress_score)

    house = sub.add_parser("house", help="histórico oficial de la Cámara (PTR PDFs)")
    house.add_argument("--members", default=None, help="nombres separados por coma")
    house.add_argument("--years", nargs="+", type=int, default=[2024, 2025, 2026])
    house.add_argument("--limit", type=int, default=None, help="limitar PTRs (pruebas)")
    house.add_argument("--out", type=Path, default=Path("data/congress/house_trades.json"))
    house.set_defaults(func=cmd_house)

    congress = sub.add_parser("congress", help="divulgaciones del Congreso (STOCK Act)")
    congress.add_argument("--member", default=None, help="nombre o parte del nombre")
    congress.add_argument("--ticker", default=None)
    congress.add_argument("--chamber", choices=["house", "senate"], default=None)
    congress.add_argument("--type", choices=["purchase", "sale", "exchange"], default=None)
    congress.add_argument("--days", type=int, default=90)
    congress.add_argument("--limit", type=int, default=40)
    congress.add_argument("--json", action="store_true")
    congress.add_argument("--health", action="store_true", help="estado y frescura del dataset")
    congress.set_defaults(func=cmd_congress)

    robustness = sub.add_parser(
        "robustness", help="promediar el demo sobre N seeds (evita conclusiones de un solo seed)"
    )
    robustness.add_argument("--seeds", type=int, default=10)
    robustness.set_defaults(func=cmd_robustness)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
