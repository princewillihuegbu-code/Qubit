from dataclasses import dataclass

MIN_CONFIDENCE = 65.0


@dataclass
class Signal:
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float


@dataclass
class ValidationResult:
    valid: bool
    reason: str


def validate_signal(signal: Signal) -> ValidationResult:
    if signal.confidence < MIN_CONFIDENCE:
        return ValidationResult(
            False,
            f"Confidence {signal.confidence:.0f}% is below the minimum threshold of {MIN_CONFIDENCE:.0f}%"
        )

    if signal.direction == "BUY":
        if signal.stop_loss >= signal.entry:
            return ValidationResult(
                False,
                f"Invalid structure: Stop Loss ({signal.stop_loss}) must be below Entry ({signal.entry}) for a BUY trade"
            )
        if signal.take_profit <= signal.entry:
            return ValidationResult(
                False,
                f"Invalid structure: Take Profit ({signal.take_profit}) must be above Entry ({signal.entry}) for a BUY trade"
            )

    elif signal.direction == "SELL":
        if signal.stop_loss <= signal.entry:
            return ValidationResult(
                False,
                f"Invalid structure: Stop Loss ({signal.stop_loss}) must be above Entry ({signal.entry}) for a SELL trade"
            )
        if signal.take_profit >= signal.entry:
            return ValidationResult(
                False,
                f"Invalid structure: Take Profit ({signal.take_profit}) must be below Entry ({signal.entry}) for a SELL trade"
            )

    return ValidationResult(True, "Signal passed all Q Validation checks")
