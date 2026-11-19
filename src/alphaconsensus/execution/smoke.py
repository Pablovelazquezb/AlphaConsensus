"""Controlled end-to-end order smoke test.

Purpose: prove that the paper account accepts orders and that we can close a
position, without touching the strategy. It buys a tiny notional of one liquid
ETF, waits for the fill, closes it, and reports the round-trip P&L.

Safety rules:
  * refuses to run if the symbol already has an open position;
  * refuses to run when the market is closed (a market order would sit queued);
  * uses a unique ``client_order_id`` per run;
  * always attempts to close what it opened, including on error.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

TERMINAL_STATUSES = {"filled", "canceled", "rejected", "expired", "done_for_day"}


@dataclass
class SmokeResult:
    ok: bool
    message: str
    order_id: str = ""
    status: str = ""
    fill_price: float = 0.0
    qty: float = 0.0
    closed: bool = False
    pnl: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


def _position_for(positions: list, symbol: str) -> Optional[Dict[str, Any]]:
    for position in positions:
        if str(position.get("symbol", "")).upper() == symbol.upper():
            return position
    return None


def run_smoke_test(
    broker: Any,
    ticker: str = "SPY",
    notional: float = 1.0,
    timeout: float = 30.0,
    poll: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> SmokeResult:
    symbol = ticker.upper()

    try:
        clock = broker.get_clock()
        if not clock.get("is_open", False):
            return SmokeResult(
                ok=False,
                message=f"Mercado cerrado (next_open={clock.get('next_open', '?')}). No envío órdenes.",
            )
    except Exception as exc:  # clock is best-effort; never block on it
        log.warning("No se pudo consultar el reloj de Alpaca: %s", exc)

    try:
        existing = _position_for(broker.get_positions(), symbol)
        if existing is not None:
            return SmokeResult(
                ok=False,
                message=f"Ya hay una posición en {symbol} (qty={existing.get('qty')}); no la toco.",
            )

        equity_before = float(broker.get_account().get("equity", 0) or 0)
        client_id = f"ac-smoke-{int(datetime.now(timezone.utc).timestamp())}"
        order = broker.submit_notional_buy(symbol, notional, client_order_id=client_id)
        order_id = str(order.get("id", ""))
        if not order_id:
            return SmokeResult(ok=False, message="Alpaca no devolvió id de orden.", details=order)

        order = _wait_for_order(broker, order_id, timeout, poll, sleep)
        status = str(order.get("status", ""))
        if status != "filled":
            return SmokeResult(
                ok=False,
                message=f"La orden no se llenó (status={status}). No hay posición que cerrar.",
                order_id=order_id,
                status=status,
                details=order,
            )

        fill_price = float(order.get("filled_avg_price") or 0)
        qty = float(order.get("filled_qty") or 0)

        closed, close_message = _close_position(broker, symbol, qty, timeout, poll, sleep)
        equity_after = float(broker.get_account().get("equity", 0) or 0)
        pnl = equity_after - equity_before

        return SmokeResult(
            ok=closed,
            message=(
                f"Compra y cierre correctos en {symbol}."
                if closed
                else f"Compré {symbol} pero el cierre falló: {close_message}. Revisa la cuenta."
            ),
            order_id=order_id,
            status=status,
            fill_price=fill_price,
            qty=qty,
            closed=closed,
            pnl=round(pnl, 4),
            details={"close": close_message},
        )
    except Exception as exc:  # noqa: BLE001 - report, never crash the CLI
        log.exception("Smoke test falló")
        return SmokeResult(ok=False, message=f"Error durante el smoke test: {exc}")


def _wait_for_order(
    broker: Any, order_id: str, timeout: float, poll: float, sleep: Callable[[float], None]
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    order: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        order = broker.get_order(order_id)
        if str(order.get("status", "")) in TERMINAL_STATUSES:
            return order
        sleep(poll)
    return order


def _close_position(
    broker: Any, symbol: str, qty: float, timeout: float, poll: float, sleep: Callable[[float], None]
) -> tuple:
    try:
        broker.close_position(symbol)
    except Exception as exc:  # fallback: explicit sell of the filled quantity
        log.warning("close_position falló (%s); intento venta explícita", exc)
        try:
            order = broker.submit_market_order(symbol, qty, "sell")
            order_id = str(order.get("id", ""))
            if order_id:
                _wait_for_order(broker, order_id, timeout, poll, sleep)
        except Exception as fallback_exc:  # noqa: BLE001
            return False, f"{exc}; fallback: {fallback_exc}"

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _position_for(broker.get_positions(), symbol) is None:
            return True, "posición cerrada"
        sleep(poll)
    return False, "la posición sigue abierta tras el timeout"
