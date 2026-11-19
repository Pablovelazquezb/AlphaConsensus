"""Alpaca paper-trading adapter (Phase 3).

Only market orders are implemented: the strategy is signal-driven and daily,
so limit/stop management can stay client-side for now. Credentials come from
ALPACA_API_KEY / ALPACA_SECRET_KEY and default to the paper endpoint — there is
no code path here that can reach a live account unless the URL is changed.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class AlpacaError(RuntimeError):
    pass


class AlpacaPaperBroker:
    name = "alpaca_paper"

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self.base_url = (
            base_url or os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2")
        ).rstrip("/")
        self.timeout = timeout
        if "paper-api" not in self.base_url:
            log.warning("ALPACA_BASE_URL no apunta al entorno paper: %s", self.base_url)

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        if not self.available:
            raise AlpacaError("Faltan ALPACA_API_KEY / ALPACA_SECRET_KEY")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.secret_key,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise AlpacaError(f"Alpaca HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AlpacaError(f"No se pudo conectar a Alpaca: {exc.reason}") from exc

    # -- API -------------------------------------------------------------
    def get_account(self) -> Dict[str, Any]:
        return self._request("GET", "/account")

    def get_positions(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/positions")

    def get_clock(self) -> Dict[str, Any]:
        return self._request("GET", "/clock")

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/orders/{order_id}")

    @staticmethod
    def format_qty(qty: float) -> str:
        """Alpaca accepts decimals for fractional longs; no trailing zeros."""
        if qty <= 0:
            raise ValueError("qty debe ser > 0")
        if float(qty).is_integer():
            return str(int(qty))
        return f"{qty:.4f}".rstrip("0").rstrip(".")

    def submit_market_order(
        self,
        ticker: str,
        qty: float,
        side: str,
        time_in_force: str = "day",
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if side not in {"buy", "sell"}:
            raise ValueError("side debe ser 'buy' o 'sell'")
        if qty <= 0:
            raise ValueError("qty debe ser > 0")
        payload = {
            "symbol": ticker.upper(),
            "qty": self.format_qty(qty),
            "side": side,
            "type": "market",
            "time_in_force": time_in_force,
        }
        if client_order_id:
            payload["client_order_id"] = client_order_id
        return self._request("POST", "/orders", payload)

    def submit_notional_buy(
        self,
        ticker: str,
        notional: float,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fractional buy expressed in dollars (Alpaca minimum is $1)."""
        if notional < 1.0:
            raise ValueError("Alpaca exige un notional mínimo de $1")
        payload = {
            "symbol": ticker.upper(),
            "notional": f"{notional:.2f}",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
        }
        if client_order_id:
            payload["client_order_id"] = client_order_id
        return self._request("POST", "/orders", payload)

    def close_position(self, ticker: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/positions/{ticker.upper()}")

    def execute_signal(self, ticker: str, side: str, qty: float) -> Dict[str, Any]:
        """Map a consensus signal side (long/short) onto an Alpaca order."""
        if side not in {"long", "short"}:
            raise ValueError("side debe ser 'long' o 'short'")
        if side == "short" and not float(qty).is_integer():
            raise ValueError(
                "Alpaca no permite fracciones en cortos: redondea a acciones enteras"
            )
        order_side = "buy" if side == "long" else "sell"
        return self.submit_market_order(ticker, qty, order_side)
