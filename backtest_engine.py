"""Transparent, event-driven SMA/ATR backtesting for Veltrix Trading Clock v7.

Execution assumptions:
- Signals are computed only after a bar closes and are filled at the next bar open.
- Stops/targets are checked against each bar's OHLC after any next-open order is filled.
- If both stop and target are touched inside one bar, the stop is assumed to hit first.
- Gaps through stop/target levels fill at the bar open, then adverse slippage is applied.
- Fees and slippage are charged on both entry and exit.
- Only one position is held at a time; no pyramiding.
- Train/test and walk-forward evaluations use fixed user parameters; no parameter optimisation occurs.
"""
from __future__ import annotations

import csv
import html
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from market_data import OHLCBar


@dataclass(frozen=True)
class BacktestConfig:
    fast_period: int = 20
    slow_period: int = 50
    atr_period: int = 14
    stop_atr_multiple: float = 2.0
    target_r_multiple: float = 2.0
    direction: str = "both"  # both, long_only, short_only
    initial_capital: float = 10_000.0
    risk_per_trade_pct: float = 0.5
    commission_bps: float = 1.0
    commission_per_unit: float = 0.0  # account-currency units per unit, per side
    slippage_bps: float = 1.0
    point_value: float = 1.0
    quantity_step: float = 0.01
    max_leverage: float = 1.0

    def validate(self) -> "BacktestConfig":
        if not (2 <= self.fast_period < self.slow_period <= 5000):
            raise ValueError("Moving-average periods must satisfy 2 ≤ fast < slow ≤ 5000.")
        if not (2 <= self.atr_period <= 5000):
            raise ValueError("ATR period must be between 2 and 5000.")
        if self.direction not in {"both", "long_only", "short_only"}:
            raise ValueError("Direction must be both, long_only or short_only.")
        positive = {
            "stop ATR multiple": self.stop_atr_multiple,
            "target R multiple": self.target_r_multiple,
            "initial capital": self.initial_capital,
            "point value": self.point_value,
            "quantity step": self.quantity_step,
            "maximum leverage": self.max_leverage,
        }
        for label, value in positive.items():
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{label.title()} must be a positive finite number.")
        if not 0 < self.risk_per_trade_pct <= 10:
            raise ValueError("Risk per trade must be greater than 0% and no more than 10%.")
        if not 0 <= self.commission_bps <= 500:
            raise ValueError("Commission must be between 0 and 500 basis points per side.")
        if not 0 <= self.commission_per_unit <= 1_000_000:
            raise ValueError("Per-unit commission must be between 0 and 1,000,000 per side.")
        if not 0 <= self.slippage_bps <= 500:
            raise ValueError("Slippage must be between 0 and 500 basis points per side.")
        return self

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "BacktestConfig":
        allowed = set(cls.__dataclass_fields__)
        cleaned = {key: values[key] for key in allowed if key in values}
        config = cls(**cleaned)
        return config.validate()


@dataclass(frozen=True)
class _Position:
    side: int
    signal_time: str
    entry_time: str
    entry_reference: float
    entry_fill: float
    quantity: float
    atr_at_signal: float
    stop_price: float
    target_price: float
    risk_amount: float
    equity_at_entry: float
    entry_fee: float
    entry_slippage_cost: float


def _normalise_bars(bars: Iterable[OHLCBar | dict[str, Any]]) -> list[OHLCBar]:
    by_timestamp: dict[datetime, OHLCBar] = {}
    for raw in bars:
        try:
            bar = raw if isinstance(raw, OHLCBar) else OHLCBar.from_dict(raw)
            stamp = bar.timestamp
            values = (bar.open, bar.high, bar.low, bar.close)
            if not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
                continue
            if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close) or bar.high < bar.low:
                continue
            by_timestamp[stamp] = bar
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    result = [by_timestamp[key] for key in sorted(by_timestamp)]
    if len(result) < 5:
        raise ValueError("At least five valid, unique OHLC bars are required.")
    return result


def _sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        if index >= period - 1:
            out[index] = running / period
    return out


def _wilder_atr(bars: list[OHLCBar], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    true_ranges: list[float] = [0.0] * len(bars)
    for index in range(1, len(bars)):
        current, previous = bars[index], bars[index - 1]
        true_ranges[index] = max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        if index == period:
            out[index] = sum(true_ranges[1:period + 1]) / period
        elif index > period and out[index - 1] is not None:
            out[index] = ((float(out[index - 1]) * (period - 1)) + true_ranges[index]) / period
    return out


def _slipped_price(reference: float, side: int, *, is_entry: bool, slippage_rate: float) -> float:
    # side=+1 long, -1 short. Entry buys a long / sells a short; exits do the reverse.
    is_buy = (side == 1 and is_entry) or (side == -1 and not is_entry)
    return reference * (1.0 + slippage_rate if is_buy else 1.0 - slippage_rate)


def _intrabar_exit(position: _Position, bar: OHLCBar) -> tuple[float, str] | None:
    """Return the reference fill and reason. Ambiguous stop/target bars are stop-first."""
    if position.side == 1:
        if bar.open <= position.stop_price:
            return bar.open, "STOP_GAP"
        if bar.open >= position.target_price:
            return bar.open, "TARGET_GAP"
        stop_hit = bar.low <= position.stop_price
        target_hit = bar.high >= position.target_price
    else:
        if bar.open >= position.stop_price:
            return bar.open, "STOP_GAP"
        if bar.open <= position.target_price:
            return bar.open, "TARGET_GAP"
        stop_hit = bar.high >= position.stop_price
        target_hit = bar.low <= position.target_price
    if stop_hit:
        return position.stop_price, "STOP" if not target_hit else "STOP_AMBIGUOUS_BAR"
    if target_hit:
        return position.target_price, "TARGET"
    return None


def _daily_sharpe(equity_curve: list[dict[str, Any]]) -> float | None:
    last_by_day: dict[str, float] = {}
    for point in equity_curve:
        stamp = datetime.fromisoformat(str(point["timestamp"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        last_by_day[stamp.date().isoformat()] = float(point["equity"])
    values = [last_by_day[key] for key in sorted(last_by_day)]
    returns = [current / previous - 1.0 for previous, current in zip(values, values[1:]) if previous > 0]
    if len(returns) < 2:
        return None
    deviation = statistics.stdev(returns)
    if deviation <= 1e-15:
        return None
    # Conventional 252-observation annualisation; this is a convention, not an asset calendar.
    return statistics.fmean(returns) / deviation * math.sqrt(252)


def _metrics(
    trades: list[dict[str, Any]], equity_curve: list[dict[str, Any]], config: BacktestConfig,
    *, bars_tested: int, exposure_bars: int,
) -> dict[str, Any]:
    net_values = [float(trade["net_pnl"]) for trade in trades]
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (None if not gross_profit else None)
    equity_values = [float(point["equity"]) for point in equity_curve]
    peak = config.initial_capital
    max_drawdown = 0.0
    for equity in equity_values:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
    final_equity = equity_values[-1] if equity_values else config.initial_capital
    total_return = (final_equity / config.initial_capital - 1.0) * 100.0
    total_commission = sum(float(item["commission"]) for item in trades)
    total_slippage = sum(float(item["slippage_cost"]) for item in trades)
    r_values = [float(item["r_multiple"]) for item in trades if item.get("r_multiple") is not None]
    return {
        "trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100.0 if trades else None,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "net_pnl": final_equity - config.initial_capital,
        "total_return_pct": total_return,
        "final_equity": final_equity,
        "max_drawdown_pct": max_drawdown,
        "sharpe_daily_annualised": _daily_sharpe(equity_curve),
        "expectancy_per_trade": statistics.fmean(net_values) if net_values else None,
        "expectancy_r": statistics.fmean(r_values) if r_values else None,
        "average_win": statistics.fmean(wins) if wins else None,
        "average_loss": abs(statistics.fmean(losses)) if losses else None,
        "total_commission": total_commission,
        "total_slippage_cost": total_slippage,
        "exposure_pct": exposure_bars / bars_tested * 100.0 if bars_tested else 0.0,
        "bars_tested": bars_tested,
        "initial_capital": config.initial_capital,
    }


def run_backtest(
    bars: Iterable[OHLCBar | dict[str, Any]], config: BacktestConfig,
    *, start_index: int = 0, end_index: int | None = None,
) -> dict[str, Any]:
    """Run a single-position SMA crossover with next-bar fills and ATR protection.

    Indicator values for a test fold can use earlier bars as warm-up context, but no
    signals/orders are processed before ``start_index``. ``end_index`` is exclusive.
    """
    config.validate()
    ordered = _normalise_bars(bars)
    end = len(ordered) if end_index is None else max(0, min(len(ordered), int(end_index)))
    start = max(0, min(end, int(start_index)))
    if end - start < 2:
        raise ValueError("The selected backtest window must contain at least two bars.")

    closes = [bar.close for bar in ordered]
    fast = _sma(closes, config.fast_period)
    slow = _sma(closes, config.slow_period)
    atr_values = _wilder_atr(ordered, config.atr_period)
    slippage_rate = config.slippage_bps / 10_000.0
    commission_rate = config.commission_bps / 10_000.0
    balance = config.initial_capital
    position: _Position | None = None
    pending: tuple[int, float | None, str] | None = None
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    exposure_bars = 0
    previous_difference: float | None = None
    if start > 0 and fast[start - 1] is not None and slow[start - 1] is not None:
        previous_difference = float(fast[start - 1]) - float(slow[start - 1])

    def commission(price: float, quantity: float) -> float:
        return price * quantity * config.point_value * commission_rate + quantity * config.commission_per_unit

    def close_position(reference_price: float, timestamp: str, reason: str) -> None:
        nonlocal balance, position
        if position is None:
            return
        exit_fill = _slipped_price(reference_price, position.side, is_entry=False, slippage_rate=slippage_rate)
        exit_fee = commission(exit_fill, position.quantity)
        gross_pnl = position.side * (exit_fill - position.entry_fill) * position.quantity * config.point_value
        net_pnl = gross_pnl - position.entry_fee - exit_fee
        exit_slippage = abs(exit_fill - reference_price) * position.quantity * config.point_value
        trade = {
            "side": "LONG" if position.side == 1 else "SHORT",
            "signal_time": position.signal_time,
            "entry_time": position.entry_time,
            "exit_time": timestamp,
            "entry_price": position.entry_fill,
            "entry_reference": position.entry_reference,
            "exit_price": exit_fill,
            "exit_reference": reference_price,
            "quantity": position.quantity,
            "point_value": config.point_value,
            "gross_pnl_after_slippage": gross_pnl,
            "commission": position.entry_fee + exit_fee,
            "slippage_cost": position.entry_slippage_cost + exit_slippage,
            "net_pnl": net_pnl,
            "risk_amount": position.risk_amount,
            "equity_at_entry": position.equity_at_entry,
            "entry_notional": position.entry_fill * position.quantity * config.point_value,
            "r_multiple": net_pnl / position.risk_amount if position.risk_amount > 0 else None,
            "exit_reason": reason,
        }
        trades.append(trade)
        balance += net_pnl
        position = None

    def open_position(side: int, atr_at_signal: float | None, signal_time: str, bar: OHLCBar) -> None:
        nonlocal position
        if side == 0 or atr_at_signal is None or not math.isfinite(atr_at_signal) or atr_at_signal <= 0:
            return
        entry_ref = bar.open
        entry_fill = _slipped_price(entry_ref, side, is_entry=True, slippage_rate=slippage_rate)
        risk_per_unit = atr_at_signal * config.stop_atr_multiple * config.point_value
        risk_budget = max(0.0, balance) * config.risk_per_trade_pct / 100.0
        if risk_per_unit <= 0 or risk_budget <= 0:
            return
        raw_quantity = risk_budget / risk_per_unit
        max_quantity = (max(0.0, balance) * config.max_leverage) / (entry_fill * config.point_value)
        quantity = min(raw_quantity, max_quantity)
        steps = math.floor((quantity + 1e-12) / config.quantity_step)
        quantity = steps * config.quantity_step
        if quantity <= 0:
            return
        stop_distance = atr_at_signal * config.stop_atr_multiple
        target_distance = stop_distance * config.target_r_multiple
        stop = entry_fill - side * stop_distance
        target = entry_fill + side * target_distance
        entry_fee = commission(entry_fill, quantity)
        entry_slippage = abs(entry_fill - entry_ref) * quantity * config.point_value
        position = _Position(
            side=side, signal_time=signal_time, entry_time=bar.timestamp.isoformat(),
            entry_reference=entry_ref, entry_fill=entry_fill, quantity=quantity,
            atr_at_signal=atr_at_signal, stop_price=stop, target_price=target,
            risk_amount=quantity * stop_distance * config.point_value,
            equity_at_entry=balance,
            entry_fee=entry_fee, entry_slippage_cost=entry_slippage,
        )

    for index in range(start, end):
        bar = ordered[index]
        # A signal from the prior bar becomes executable at this bar's open.
        if pending is not None:
            target_side, signal_atr, signal_timestamp = pending
            if position is not None and target_side != position.side:
                close_position(bar.open, bar.timestamp.isoformat(), "SIGNAL_REVERSAL" if target_side else "SIGNAL_EXIT")
            if position is None and target_side != 0:
                open_position(target_side, signal_atr, signal_timestamp, bar)
            pending = None

        # Evaluate the complete bar only after the opening fill. Ambiguous stop/target hits are conservative.
        was_exposed_this_bar = position is not None
        if position is not None:
            triggered = _intrabar_exit(position, bar)
            if triggered:
                reference, reason = triggered
                close_position(reference, bar.timestamp.isoformat(), reason)

        if was_exposed_this_bar:
            exposure_bars += 1
        if position is not None:
            expected_exit_fee = commission(bar.close, position.quantity)
            expected_exit_slippage = bar.close * slippage_rate * position.quantity * config.point_value
            unrealised = position.side * (bar.close - position.entry_fill) * position.quantity * config.point_value
            marked_equity = balance + unrealised - position.entry_fee - expected_exit_fee - expected_exit_slippage
        else:
            marked_equity = balance
        equity_curve.append({"timestamp": bar.timestamp.isoformat(), "equity": marked_equity})

        # Compute a crossover from this completed bar. It cannot fill until the next bar.
        if fast[index] is not None and slow[index] is not None:
            difference = float(fast[index]) - float(slow[index])
            if previous_difference is not None:
                bullish_cross = previous_difference <= 0 and difference > 0
                bearish_cross = previous_difference >= 0 and difference < 0
                target_side = 0
                crossed = bullish_cross or bearish_cross
                if crossed:
                    if config.direction == "both":
                        target_side = 1 if bullish_cross else -1
                    elif config.direction == "long_only" and bullish_cross:
                        target_side = 1
                    elif config.direction == "long_only" and bearish_cross:
                        target_side = 0
                    elif config.direction == "short_only" and bearish_cross:
                        target_side = -1
                    elif config.direction == "short_only" and bullish_cross:
                        target_side = 0
                    if (position is not None and target_side != position.side) or (position is None and target_side != 0):
                        pending = (target_side, atr_values[index], bar.timestamp.isoformat())
            previous_difference = difference

    # Close any remaining exposure at the final available close, never beyond the data window.
    if position is not None:
        final_bar = ordered[end - 1]
        close_position(final_bar.close, final_bar.timestamp.isoformat(), "END_OF_TEST_WINDOW")
        equity_curve.append({"timestamp": final_bar.timestamp.isoformat(), "equity": balance})
    if not equity_curve:
        equity_curve = [{"timestamp": ordered[start].timestamp.isoformat(), "equity": balance}]
    metrics = _metrics(trades, equity_curve, config, bars_tested=end - start, exposure_bars=exposure_bars)
    return {
        "metrics": metrics,
        "trades": trades,
        "equity_curve": equity_curve,
        "start_timestamp": ordered[start].timestamp.isoformat(),
        "end_timestamp": ordered[end - 1].timestamp.isoformat(),
        "bars_tested": end - start,
        "config": asdict(config),
        "methodology": "SMA crossover calculated at bar close; next-bar-open execution; Wilder ATR stop; R-multiple target; conservative stop-first OHLC handling; fees and slippage on both sides.",
    }


def run_out_of_sample(
    bars: Iterable[OHLCBar | dict[str, Any]], config: BacktestConfig, *, train_fraction: float = 0.70,
) -> dict[str, Any]:
    ordered = _normalise_bars(bars)
    if not 0.50 <= train_fraction <= 0.85:
        raise ValueError("Training fraction must be between 50% and 85%.")
    split = int(len(ordered) * train_fraction)
    warmup = max(config.slow_period, config.atr_period) + 2
    if split < warmup or len(ordered) - split < 5:
        raise ValueError(
            f"Not enough bars for chronological holdout. Need at least {warmup} training bars and 5 test bars; "
            f"received {split} and {len(ordered) - split}."
        )
    train = run_backtest(ordered[:split], config)
    test = run_backtest(ordered, config, start_index=split, end_index=len(ordered))
    return {
        "train": train,
        "test": test,
        "split_index": split,
        "split_timestamp": ordered[split].timestamp.isoformat(),
        "train_fraction": train_fraction,
        "methodology": "Chronological holdout. Fixed strategy parameters are used unchanged in train and test; indicators use pre-test history for warm-up, but no positions are carried across the split.",
    }


def run_walk_forward(
    bars: Iterable[OHLCBar | dict[str, Any]], config: BacktestConfig, *, train_fraction: float = 0.50,
    folds: int = 3,
) -> dict[str, Any]:
    ordered = _normalise_bars(bars)
    if not 0.40 <= train_fraction <= 0.80:
        raise ValueError("Walk-forward initial training fraction must be between 40% and 80%.")
    if not 2 <= folds <= 10:
        raise ValueError("Walk-forward folds must be between 2 and 10.")
    initial_train = max(int(len(ordered) * train_fraction), max(config.slow_period, config.atr_period) + 2)
    remaining = len(ordered) - initial_train
    test_size = remaining // folds if folds else 0
    if test_size < 5:
        raise ValueError(
            f"Not enough data for {folds} walk-forward folds. Each test fold needs at least 5 bars "
            "after the initial training period. Import more history or reduce the fold count."
        )
    results: list[dict[str, Any]] = []
    for fold_index in range(folds):
        start = initial_train + fold_index * test_size
        end = len(ordered) if fold_index == folds - 1 else start + test_size
        result = run_backtest(ordered, config, start_index=start, end_index=end)
        metrics = result["metrics"]
        results.append({
            "fold": fold_index + 1,
            "training_bars": start,
            "test_bars": end - start,
            "train_end": ordered[start - 1].timestamp.isoformat(),
            "test_start": ordered[start].timestamp.isoformat(),
            "test_end": ordered[end - 1].timestamp.isoformat(),
            **metrics,
            "trades": result["trades"],
        })
    return {
        "folds": results,
        "initial_train_bars": initial_train,
        "fold_count": len(results),
        "methodology": "Expanding-history walk-forward evaluation with fixed parameters. Each test fold starts flat; earlier bars are indicator warm-up only. No parameter fitting or optimisation is performed.",
    }


def export_trades_csv(path: str | Path, trades: list[dict[str, Any]]) -> Path:
    destination = Path(path)
    fields = ["side", "signal_time", "entry_time", "exit_time", "entry_price", "exit_price", "quantity",
              "point_value", "gross_pnl_after_slippage", "commission", "slippage_cost", "net_pnl",
              "risk_amount", "equity_at_entry", "entry_notional", "r_multiple", "exit_reason"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
    return destination


def export_backtest_html(
    path: str | Path, *, asset_name: str, source: str, interval_minutes: float,
    config: BacktestConfig, oos: dict[str, Any], walk_forward: dict[str, Any],
    sampling_label: str = "Time-based OHLC bars",
    generated_at: datetime | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    generated = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    def esc(value: Any) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, float):
            return f"{value:.4f}"
        return html.escape(str(value))
    metrics = [
        ("Trades", "trade_count"), ("Net P&L", "net_pnl"), ("Total return %", "total_return_pct"),
        ("Win rate %", "win_rate_pct"), ("Profit factor", "profit_factor"),
        ("Max drawdown %", "max_drawdown_pct"), ("Daily Sharpe (annualised)", "sharpe_daily_annualised"),
        ("Expectancy / trade", "expectancy_per_trade"), ("Expectancy R", "expectancy_r"),
        ("Commission", "total_commission"), ("Estimated slippage", "total_slippage_cost"),
    ]
    train_metrics = oos["train"]["metrics"]
    test_metrics = oos["test"]["metrics"]
    train_metric_html = "".join(f"<tr><th>{html.escape(label)}</th><td>{esc(train_metrics.get(key))}</td></tr>" for label, key in metrics)
    metric_html = "".join(f"<tr><th>{html.escape(label)}</th><td>{esc(test_metrics.get(key))}</td></tr>" for label, key in metrics)
    trade_rows = []
    for item in oos["test"]["trades"]:
        trade_rows.append("<tr>" + "".join(f"<td>{esc(item.get(key))}</td>" for key in (
            "side", "entry_time", "exit_time", "entry_price", "exit_price", "quantity", "net_pnl", "r_multiple", "exit_reason"
        )) + "</tr>")
    fold_rows = []
    for item in walk_forward["folds"]:
        fold_rows.append("<tr>" + "".join(f"<td>{esc(item.get(key))}</td>" for key in (
            "fold", "training_bars", "test_bars", "test_start", "test_end", "trade_count", "net_pnl",
            "total_return_pct", "max_drawdown_pct", "sharpe_daily_annualised"
        )) + "</tr>")
    doc = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Veltrix Strategy Backtest Report</title><style>
body{{font:14px Segoe UI,Arial,sans-serif;background:#08131c;color:#d8e8ef;margin:30px}}h1,h2{{color:#48d9e6}}p{{color:#a7bdc8}}table{{border-collapse:collapse;width:100%;margin:14px 0;background:#0d202b}}th,td{{border:1px solid #24424f;padding:8px;text-align:left;white-space:nowrap}}th{{background:#12303d;color:#72edf0}}tr:nth-child(even){{background:#102630}}.wrap{{overflow-x:auto}}.note{{border-left:3px solid #48d9e6;background:#10232c;padding:12px}}
</style></head><body><h1>VELTRIX CAPITAL · STRATEGY RESEARCH</h1>
<p>Generated {html.escape(generated)} · UTC</p><p>Instrument: {html.escape(asset_name)} · Source: {html.escape(source)} · Sampling: {html.escape(sampling_label)} · Median elapsed time: {interval_minutes:.2f} minutes</p>
<div class='note'><strong>Execution model:</strong> Signals are calculated at bar close and filled at the next bar open. Stop/target ambiguity is resolved stop-first using OHLC, including for tick-derived bars; this is not tick-by-tick order replay. Gaps fill at the open. Costs are charged on entry and exit. Parameters are fixed; no optimisation is performed. This is a research simulation, not a guarantee of future performance.</div>
<h2>Strategy parameters</h2><p>{html.escape(str(asdict(config)))}</p><h2>In-sample reference metrics</h2><div class='wrap'><table>{train_metric_html}</table></div>
<h2>Chronological holdout · Out-of-sample test metrics</h2><div class='wrap'><table>{metric_html}</table></div>
<h2>Out-of-sample trade log</h2><div class='wrap'><table><thead><tr>{''.join(f'<th>{x}</th>' for x in ('Side','Entry time','Exit time','Entry','Exit','Quantity','Net P&L','R','Reason'))}</tr></thead><tbody>{''.join(trade_rows)}</tbody></table></div>
<h2>Walk-forward folds · Fixed parameters</h2><p>{html.escape(walk_forward['methodology'])}</p><div class='wrap'><table><thead><tr>{''.join(f'<th>{x}</th>' for x in ('Fold','Train bars','Test bars','Test start','Test end','Trades','Net P&L','Return %','Max DD %','Daily Sharpe'))}</tr></thead><tbody>{''.join(fold_rows)}</tbody></table></div>
<h2>Methodology and caveats</h2><p>{html.escape(oos['methodology'])}</p><p>Daily Sharpe uses observed UTC daily equity changes and conventional √252 annualisation. Maximum drawdown uses the marked-to-market bar equity curve. Position sizing is risk-budget divided by ATR stop distance, capped by maximum leverage and rounded down to quantity step. For event-driven bars, elapsed time between bars varies; median elapsed time is descriptive only. The engine does not replay quotes, trades, queue position, or the exact intrabar stop/target sequence. Contract multiplier and quantity step must match the broker/instrument specification.</p>
</body></html>"""
    destination.write_text(doc, encoding="utf-8")
    return destination
