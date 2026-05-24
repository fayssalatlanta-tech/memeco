from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

MIN_TRADE_AMOUNT_SOL = 0.1
MIN_TRADES_FOR_SCORE = 5
BOT_TX_PER_MINUTE = 5.0
ELITE_THRESHOLD = 75.0
WATCHLIST_THRESHOLD = 55.0
MAX_ROI_FOR_FULL_SCORE = 500.0
MAX_30D_PROFIT_FOR_FULL_SCORE_SOL = 100.0

WIN_RATE_WEIGHT = 0.35
ROI_WEIGHT = 0.25
EARLY_ENTRY_WEIGHT = 0.20
CONSISTENCY_WEIGHT = 0.20


@dataclass(frozen=True)
class WhaleTrade:
    amount_sol: float
    pnl_sol: float | None = None
    roi_percent: float | None = None
    minutes_after_launch: float | None = None
    tx_per_minute: float = 0.0


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def valid_whale_trades(trades: list[WhaleTrade]) -> list[WhaleTrade]:
    return [trade for trade in trades if trade.amount_sol >= MIN_TRADE_AMOUNT_SOL]


def is_bot_like_wallet(trades: list[WhaleTrade]) -> bool:
    return any(trade.tx_per_minute > BOT_TX_PER_MINUTE for trade in trades)


def win_rate_score(trades: list[WhaleTrade]) -> float:
    if len(trades) < MIN_TRADES_FOR_SCORE:
        return 0.0

    wins = sum(1 for trade in trades if (trade.pnl_sol or 0) > 0)
    return (wins / len(trades)) * 100


def roi_score(trades: list[WhaleTrade]) -> float:
    roi_values = [trade.roi_percent for trade in trades if trade.roi_percent is not None]
    if not roi_values:
        return 0.0

    avg_roi = mean(roi_values)
    return clamp_score((avg_roi / MAX_ROI_FOR_FULL_SCORE) * 100)


def early_entry_score(trades: list[WhaleTrade]) -> float:
    entry_values = [
        trade.minutes_after_launch
        for trade in trades
        if trade.minutes_after_launch is not None and trade.minutes_after_launch >= 0
    ]
    if not entry_values:
        return 0.0

    avg_entry_minutes = mean(entry_values)
    if avg_entry_minutes <= 2:
        return 100.0
    if avg_entry_minutes <= 10:
        return 50.0
    return 0.0


def consistency_score(trades: list[WhaleTrade]) -> float:
    total_profit = sum(trade.pnl_sol or 0 for trade in trades)
    return clamp_score((total_profit / MAX_30D_PROFIT_FOR_FULL_SCORE_SOL) * 100)


def whale_score_breakdown(trades: list[WhaleTrade]) -> dict:
    valid_trades = valid_whale_trades(trades)
    bot_flag = is_bot_like_wallet(valid_trades)

    if len(valid_trades) < MIN_TRADES_FOR_SCORE or bot_flag:
        return {
            "win_rate_score": 0.0,
            "roi_score": 0.0,
            "early_entry_score": 0.0,
            "consistency_score": 0.0,
            "win_rate_points": 0.0,
            "roi_points": 0.0,
            "early_entry_points": 0.0,
            "consistency_points": 0.0,
            "score": 0.0,
            "score_10": 0.0,
            "score_reason": "BOT_LIKE" if bot_flag else "INSUFFICIENT_TRADES",
        }

    w_score = win_rate_score(valid_trades)
    r_score = roi_score(valid_trades)
    e_score = early_entry_score(valid_trades)
    c_score = consistency_score(valid_trades)
    w_points = w_score * WIN_RATE_WEIGHT
    r_points = r_score * ROI_WEIGHT
    e_points = e_score * EARLY_ENTRY_WEIGHT
    c_points = c_score * CONSISTENCY_WEIGHT
    final_score = round(w_points + r_points + e_points + c_points, 2)

    return {
        "win_rate_score": round(w_score, 2),
        "roi_score": round(r_score, 2),
        "early_entry_score": round(e_score, 2),
        "consistency_score": round(c_score, 2),
        "win_rate_points": round(w_points, 2),
        "roi_points": round(r_points, 2),
        "early_entry_points": round(e_points, 2),
        "consistency_points": round(c_points, 2),
        "score": final_score,
        "score_10": round(final_score / 10, 2),
        "score_reason": "SCORED",
    }


def calculate_whale_reliability(trades: list[WhaleTrade]) -> float:
    return whale_score_breakdown(trades)["score"]


def summarize_whale_trades(trades: list[WhaleTrade]) -> dict:
    valid_trades = valid_whale_trades(trades)
    roi_values = [trade.roi_percent for trade in valid_trades if trade.roi_percent is not None]
    entry_values = [
        trade.minutes_after_launch
        for trade in valid_trades
        if trade.minutes_after_launch is not None and trade.minutes_after_launch >= 0
    ]
    wins = sum(1 for trade in valid_trades if (trade.pnl_sol or 0) > 0)
    total_profit = sum(trade.pnl_sol or 0 for trade in valid_trades)
    score_breakdown = whale_score_breakdown(valid_trades)

    return {
        "trade_count": len(valid_trades),
        "profitable_trade_count": wins,
        "win_rate_percent": round((wins / len(valid_trades)) * 100, 2) if valid_trades else 0,
        "total_profit_sol": round(total_profit, 6),
        "total_profit_30d_sol": round(total_profit, 6),
        "avg_roi_percent": round(mean(roi_values), 2) if roi_values else 0,
        "avg_minutes_after_launch": round(mean(entry_values), 2) if entry_values else None,
        "bot_flag": is_bot_like_wallet(valid_trades),
        "reliability_score": score_breakdown["score"],
        "reliability_score_10": score_breakdown["score_10"],
        "score_breakdown": score_breakdown,
    }


def classify_elite_wallet(summary: dict) -> str:
    if summary.get("bot_flag"):
        return "BOT_EXCLUDED"
    if summary.get("reliability_score", 0) >= ELITE_THRESHOLD:
        return "ELITE_SMART_MONEY"
    if summary.get("reliability_score", 0) >= WATCHLIST_THRESHOLD:
        return "WATCHLIST_CANDIDATE"
    return "UNPROVEN"
