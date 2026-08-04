# src/etorobot/validate.py
"""Supervised real-money validation round-trip.

This harness is run BY THE USER, interactively. Every money-moving step
requires a typed confirmation, and every raw API response is persisted so
real response shapes can be diffed against the demo shapes the parsers
were built on. Any failure after the order is placed still persists the
log and reports the possibly-open position.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone


def _write(log: dict, out_path: str, print_fn) -> dict:
    with open(out_path, "w") as f:
        json.dump(log, f, indent=2, default=str)
    print_fn(f"Raw responses saved to {out_path}")
    return log


async def _sl_tp(client, instrument_id: int,
                 symbol: str) -> tuple[float | None, float | None]:
    # Derive a wide protective bracket (±5%) from the last candle so the
    # validation order carries SL/TP like production orders do. Best-effort:
    # if the price can't be fetched the order goes out unprotected and the
    # harness says so.
    try:
        candles = await client.get_candles(instrument_id, symbol,
                                           "OneMinute", count=1)
        if candles:
            last = candles[-1].close
            return round(last * 0.95, 6), round(last * 1.05, 6)
    except Exception:
        pass
    return None, None


async def run_validation(client, symbol: str, amount: float, out_path: str,
                         input_fn=input, print_fn=print,
                         poll_attempts: int = 40,
                         poll_interval: float = 0.5) -> dict:
    log: dict = {"symbol": symbol, "amount": amount, "aborted": None,
                 "steps": {}}
    iid = await client.resolve_instrument(symbol)
    portfolio = await client.get_portfolio()
    log["steps"]["portfolio_before"] = portfolio
    print_fn(f"Instrument {symbol} -> {iid}")
    credit = portfolio.get("clientPortfolio", {}).get("credit")
    print_fn(f"Available credit: {credit}")

    sl, tp = await _sl_tp(client, iid, symbol)
    print_fn(f"About to OPEN a market BUY of ${amount} {symbol} "
             f"(SL {sl}, TP {tp}).")
    if sl is None:
        print_fn("WARNING: no SL/TP could be derived — the position will be "
                 "unprotected until closed.")
    if input_fn("Type 'open' to place the order (anything else aborts): ") \
            != "open":
        log["aborted"] = "before-open"
        print_fn("Aborted before open. No orders placed.")
        return _write(log, out_path, print_fn)

    order = await client.create_order(symbol=symbol, instrument_id=iid,
                                      transaction="buy", amount=amount,
                                      stop_loss=sl, take_profit=tp)
    log["steps"]["open_response"] = order
    print_fn(f"Open response: {json.dumps(order)}")
    order_id = order.get("orderId")
    if order_id is None:
        # Discovering shape differences is this harness's purpose: report
        # rather than crash on an unguarded subscript.
        log["aborted"] = "open-shape-unexpected"
        print_fn("Open response carried no orderId — the real response shape "
                 "differs from demo. Check the eToro app for the order and "
                 "inspect the saved JSON.")
        return _write(log, out_path, print_fn)

    position_id: str | None = None
    try:
        info: dict = {}
        for _ in range(poll_attempts):
            info = await client.get_order(order_id)
            if info.get("positions") or info.get("errorCode"):
                break
            await asyncio.sleep(poll_interval)
        log["steps"]["order_status"] = info
        print_fn(f"Order status: {json.dumps(info)}")
        if info.get("errorCode"):
            log["aborted"] = "order-rejected"
            print_fn(f"Order REJECTED by eToro: "
                     f"{info.get('errorMessage') or info.get('errorCode')}. "
                     f"It will not fill.")
            return _write(log, out_path, print_fn)
        positions = info.get("positions") or []
        if not positions:
            log["aborted"] = "order-unresolved"
            print_fn("Order did not resolve into a position. Check the eToro "
                     "app before retrying — it may still fill.")
            return _write(log, out_path, print_fn)
        position_id = str(positions[0]["positionID"])
        print_fn(f"Filled: position {position_id} at rate "
                 f"{positions[0]['rate']}")

        if input_fn(f"Type 'close' to close position {position_id} "
                    f"(anything else aborts): ") != "close":
            log["aborted"] = "before-close"
            print_fn(f"Aborted with OPEN position {position_id} — close it "
                     f"in the eToro app, or re-run and close there.")
            return _write(log, out_path, print_fn)

        close = await client.close_position(position_id, iid)
        log["steps"]["close_response"] = close
        print_fn(f"Close response: {json.dumps(close)}")

        min_date = (datetime.now(timezone.utc)
                    - timedelta(days=1)).strftime("%Y-%m-%d")
        settle: dict | None = None
        for _ in range(poll_attempts):
            trades = await client.get_trade_history(min_date)
            for trade in trades:
                if str(trade.get("positionId")) == position_id:
                    settle = trade
                    break
            if settle is not None:
                break
            await asyncio.sleep(poll_interval)
        if settle is None:
            log["aborted"] = "close-unsettled"
            print_fn("Close did not appear in trade history yet; verify in "
                     "the eToro app.")
            return _write(log, out_path, print_fn)
        log["steps"]["close_settle"] = settle
        print_fn(f"Close settled: {json.dumps(settle)}")
        print_fn("Round trip complete.")
        return _write(log, out_path, print_fn)
    except Exception as exc:
        # Never lose the evidence or the open-position warning: persist what
        # we have, name the position (or order) to chase, then re-raise.
        log["error"] = repr(exc)
        ref = position_id or order_id
        print_fn(f"ERROR after order placement: {exc!r}")
        print_fn(f"A position may be OPEN (ref {ref}) — check the eToro app "
                 f"and close it manually if needed.")
        _write(log, out_path, print_fn)
        raise
