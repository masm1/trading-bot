from ml_optimizer import predict_signal_quality
from config import (
    CALL_SIGNAL_THRESHOLD_PERCENT,
    FADE_SIGNAL_THRESHOLD_PERCENT,
    PUT_SIGNAL_THRESHOLD_PERCENT,
)


def detect_signal(base_price, current_price):
    if base_price <= 0:
        return {
            "signal": "ERROR",
            "change_percent": 0,
            "message": "Base price must be greater than zero.",
        }

    change_percent = ((current_price - base_price) / base_price) * 100

    if change_percent <= PUT_SIGNAL_THRESHOLD_PERCENT:
        signal = "STRONG_DROP"
    elif change_percent >= CALL_SIGNAL_THRESHOLD_PERCENT:
        signal = "STRONG_RALLY"
    elif change_percent >= FADE_SIGNAL_THRESHOLD_PERCENT:
        signal = "POP_FADE"
    else:
        signal = "NO_SIGNAL"

    signal_code = 1 if change_percent > 0 else 0
    quality = predict_signal_quality(change_percent / 100, signal_code)  # Normalize change_percent

    return {
        "signal": signal,
        "change_percent": round(change_percent, 2),
        "quality": round(quality, 2),
        "message": "",
    }


def paper_action_for_signal(signal_info):
    signal = signal_info.get("signal", "NO_SIGNAL")
    quality = signal_info.get("quality", 0.5)

    base_action = {
        "STRONG_DROP": "PUT IDEA: bearish move / short setup",
        "POP_FADE": "PUT IDEA: pop-and-fade setup",
        "STRONG_RALLY": "CALL IDEA: bullish momentum setup",
        "NO_SIGNAL": "PAPER EVALUATION: no trade signal",
    }.get(signal, "NO ACTION")

    if signal != "NO_SIGNAL" and quality < 0.6:
        base_action += f" (Low confidence: {quality:.1%})"

    return base_action


def demo_direction_for_signal(signal):
    if signal == "STRONG_DROP":
        return "SELL"
    if signal == "POP_FADE":
        return "SELL"
    if signal == "STRONG_RALLY":
        return "BUY"

    return None


def signal_score(signal, change_percent):
    priority = {
        "STRONG_DROP": 3,
        "POP_FADE": 2,
        "STRONG_RALLY": 1,
        "NO_SIGNAL": 0,
    }
    return priority.get(signal, 0), abs(change_percent)
