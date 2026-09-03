import asyncio
import yfinance as yf
import pandas as pd
import numpy as np
import csv
from pathlib import Path
from datetime import datetime
import broker
from broker.robinhood_broker import RobinhoodBroker
from broker.execution_ticket import build_execution_ticket
from broker.robinhood_review_bridge import (
    SanitizedOrderDetails,
    ReviewEquityOrderCapability,
    request_broker_review,
)
from broker.robinhood_mcp_session import open_mcp_session
import json

BROKER_QUEUE_FILE = Path("Data/broker_queue.json")
TEST_MODE = True
HISTORY_FILE = Path( "Data/scan_history.csv")
REPORTS_DIR = Path("Reports")

async def review_triggered_order(symbol, quantity=1, triggered_today=False):
    if triggered_today is not True:
        raise RuntimeError("Broker review blocked: triggered_today is required")
    order = SanitizedOrderDetails(
        symbol=symbol,
        side="buy",
        order_type="market",
        quantity=quantity,
    )

    async with open_mcp_session() as session:
        return await request_broker_review(
            order,
            ReviewEquityOrderCapability(),
            session,
        )

# ============================================================
# TRADEPILOTAI - VERSION 3
# DAILY CHART ONLY
#
# Strategy:
#   1. Stock price $3-$50
#   2. Average daily volume >= 1 million
#   3. Daily MACD setup
#   4. MACD and Signal below zero
#   5. Histogram is improving from negative territory
#   6. Identify the setup candle
#   7. Entry = break of setup candle high
#   8. Identify daily support/resistance
#   9. Target = nearest valid daily swing high above entry
#  10. Grade the setup
#
# IMPORTANT:
#   This version does NOT place trades.
#   It is analysis/scanning only.
# ============================================================


# ============================================================
# SETTINGS
# ============================================================

MIN_PRICE = 3.00
MAX_PRICE = 50.00

MIN_AVG_VOLUME = 1_000_000

# DAILY ONLY
TIMEFRAME = "1d"
DATA_PERIOD = "1y"

# MACD settings
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Number of daily candles used to search for setups
SETUP_LOOKBACK = 100

# Number of daily candles used for support/resistance
SR_LOOKBACK = 100

# Minimum upside required from entry to target
MIN_TARGET_UPSIDE = 0.01

# Maximum distance from support to consider entry
SUPPORT_DISTANCE = 0.05


# ============================================================
# WATCHLIST
# ============================================================

WATCHLIST = [
    "JBLU",
    "DNUT",
    "SOFI",
    "PLUG",
    "SIRI",
    "OPEN",
    "LCID",
    "NOK",
    "AMC",
    "F",
]


# ============================================================
# DATA DOWNLOAD
# ============================================================

def get_daily_data(symbol):

    try:

        data = yf.download(
            symbol,
            period=DATA_PERIOD,
            interval=TIMEFRAME,
            auto_adjust=False,
            progress=False
        )

        if data.empty:
            return None

        # Handle yfinance MultiIndex columns
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        required = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
        ]

        for column in required:
            if column not in data.columns:
                return None

        data = data.dropna()

        return data

    except Exception as error:

        print(f"ERROR downloading {symbol}: {error}")

        return None


# ============================================================
# MACD
# ============================================================

def calculate_macd(data):

    close = data["Close"].astype(float)

    ema_fast = close.ewm(
        span=MACD_FAST,
        adjust=False
    ).mean()

    ema_slow = close.ewm(
        span=MACD_SLOW,
        adjust=False
    ).mean()

    macd = ema_fast - ema_slow

    signal = macd.ewm(
        span=MACD_SIGNAL,
        adjust=False
    ).mean()

    histogram = macd - signal

    data = data.copy()

    data["MACD"] = macd
    data["Signal"] = signal
    data["Histogram"] = histogram

    return data


# ============================================================
# FIND DAILY MACD SETUP
# ============================================================

def find_macd_setup(data):

    data = calculate_macd(data)

    if len(data) < 40:
        return None

    recent = data.tail(SETUP_LOOKBACK).copy()

    setup = None

    # ========================================================
    # DAILY MACD BUY SETUP
    #
    # We are looking for the EARLY bullish transition:
    #
    # 1. MACD is below zero
    # 2. Signal is below zero
    # 3. Histogram is still negative
    # 4. Histogram is getting less negative
    # 5. This creates the "light red" recovery area
    #
    # The candle high becomes the entry trigger.
    #
    # DAILY CHART ONLY.
    # ========================================================

    for i in range(2, len(recent)):
         # DEBUG: show why each daily candle passes/fails
        if i >= len(recent) - 10:
            two_back_debug = recent.iloc[i - 2]
            previous_debug = recent.iloc[i - 1]
            current_debug = recent.iloc[i]

            macd_debug = float(current_debug["MACD"])
            signal_debug = float(current_debug["Signal"])
            hist_debug = float(current_debug["Histogram"])

            prev_hist_debug = float(previous_debug["Histogram"])
            two_back_hist_debug = float(two_back_debug["Histogram"])

          

            print(f"MACD BELOW ZERO:    {macd_debug < 0}")
            print(f"SIGNAL BELOW ZERO:  {signal_debug < 0}")
            print(f"HIST NEGATIVE:      {hist_debug < 0}")
            print(f"HIST IMPROVING:      {hist_debug > prev_hist_debug}")
            print(
                f"2-DAY IMPROVEMENT:  "
                f"{hist_debug > prev_hist_debug > two_back_hist_debug}"
            )
            print(
                f"SIGNAL TURNING UP:  "
                f"{signal_debug > float(previous_debug['Signal'])}"
            )

        two_back = recent.iloc[i - 2]
        previous = recent.iloc[i - 1]
        current = recent.iloc[i]

        macd = float(current["MACD"])
        signal = float(current["Signal"])
        histogram = float(current["Histogram"])

        previous_histogram = float(
            previous["Histogram"]
        )

        two_back_histogram = float(
            two_back["Histogram"]
        )

        # ----------------------------------------------------
        # MACD and signal must remain below zero
        # ----------------------------------------------------

        macd_below_zero = macd < 0
        signal_below_zero = signal < 0

        # ----------------------------------------------------
        # Histogram remains negative but is improving
        #
        # Example:
        #
        # -0.08 → -0.05 → -0.02
        #
        # This is the bullish recovery area.
        # ----------------------------------------------------

        histogram_negative = histogram < 0

        histogram_improving = (
            histogram > previous_histogram
        )

        previous_histogram_improving = (
            previous_histogram > two_back_histogram
        )

        # ----------------------------------------------------
        # We want TWO consecutive improvements.
        # This helps avoid a random one-day bounce.
        # ----------------------------------------------------

        bullish_histogram_recovery = (
            histogram_negative
            and histogram_improving
            and previous_histogram_improving
        )

        # ----------------------------------------------------
        # Signal line should also be beginning to turn upward.
        # ----------------------------------------------------

        signal_turning_up = (
            signal > float(previous["Signal"])
        )

        # ----------------------------------------------------
        # FINAL DAILY SETUP
        # ----------------------------------------------------

        if (
            macd_below_zero
            and signal_below_zero
            and histogram_negative
            and histogram_improving
        ):

            setup = {
                "date": recent.index[i],

                "open": float(
                    current["Open"]
                ),

                "high": float(
                    current["High"]
                ),

                "low": float(
                    current["Low"]
                ),

                "close": float(
                    current["Close"]
                ),

                "macd": macd,

                "signal": signal,

                "histogram": histogram,

                "previous_histogram":
                    previous_histogram,

                "setup_type":
                    "DAILY MACD BULLISH RECOVERY",

                "histogram_state":
                    "NEGATIVE BUT IMPROVING"
            }
            

    return setup


# ============================================================
# DAILY SWING HIGHS / LOWS
# ============================================================

def find_swing_levels(data):

    recent = data.tail(SR_LOOKBACK)

    swing_highs = []
    swing_lows = []

    for i in range(2, len(recent) - 2):

        current_high = float(
            recent["High"].iloc[i]
        )

        current_low = float(
            recent["Low"].iloc[i]
        )

        left_high_1 = float(
            recent["High"].iloc[i - 1]
        )

        left_high_2 = float(
            recent["High"].iloc[i - 2]
        )

        right_high_1 = float(
            recent["High"].iloc[i + 1]
        )

        right_high_2 = float(
            recent["High"].iloc[i + 2]
        )

        left_low_1 = float(
            recent["Low"].iloc[i - 1]
        )

        left_low_2 = float(
            recent["Low"].iloc[i - 2]
        )

        right_low_1 = float(
            recent["Low"].iloc[i + 1]
        )

        right_low_2 = float(
            recent["Low"].iloc[i + 2]
        )

        # Swing high
        if (
            current_high > left_high_1
            and current_high > left_high_2
            and current_high > right_high_1
            and current_high > right_high_2
        ):

            swing_highs.append(
               {
                    "date": recent.index[i],
                    "price": current_high
               }
            )

        # Swing low
        if (
            current_low < left_low_1
            and current_low < left_low_2
            and current_low < right_low_1
            and current_low < right_low_2
        ):

            swing_lows.append(
                {
                    "date": recent.index[i],
                    "price": current_low
                }
            )

    return swing_highs, swing_lows


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def find_support_resistance(data):

    swing_highs, swing_lows = find_swing_levels(
        data
    )

    current_price = float(
        data["Close"].iloc[-1]
    )

    # Resistance above current price
    resistance_levels = [
        level
        for level in swing_highs
        if level["price"] > current_price
    ]

    # Support below current price
    support_levels = [
        level
        for level in swing_lows
        if level["price"] < current_price
    ]

    if resistance_levels:

        resistance = min(
            resistance_levels,
            key=lambda level: level["price"]
        )

    else:

        resistance = None

    if support_levels:

        support = max(
            support_levels,
            key=lambda level: level["price"]
        )

    else:

        support = None

    return support, resistance, swing_highs, swing_lows


# ============================================================
# ENTRY
# ============================================================

def calculate_entry(data, setup):

    if setup is None:
        return None

    setup_date = setup["date"]

    setup_high = setup["high"]

    # --------------------------------------------------------
    # The setup candle high becomes our entry trigger.
    #
    # We DO NOT buy merely because the MACD condition exists.
    #
    # Price must break the setup candle high.
    # --------------------------------------------------------

    candles_after = data[
        data.index > setup_date
    ]

    triggered = False
    trigger_date = None
    latest_date = data.index[-1]

    for date, candle in candles_after.iterrows():

        candle_high = float(
            candle["High"]
        )

        if candle_high > setup_high:

            triggered = True
            trigger_date = date

            break
            latest_date = data.index[-1]

    triggered_today = (
        triggered
        and trigger_date == latest_date
    )

    return {
        "entry_price": setup_high,
        "triggered": triggered,
        "triggered_today": triggered_today,
        "trigger_date": trigger_date
    }


# ============================================================
# TARGET
# ============================================================

def calculate_target(
    entry_price,
    swing_highs
):

    valid_targets = [
        level
        for level in swing_highs
        if level["price"] > entry_price
    ]

    if not valid_targets:
        return None

    closest_target = min(
        valid_targets,
        key=lambda level: level["price"]
    )

    return closest_target

def calculate_trade_status(
    data,
    entry,
    target,    
    entry_price,
    swing_highs
):
    if entry is None:
        return "No Entry"
    if target is None:
        return "No Target"
    if not entry["triggered"]:
        return "waiting"
        
    trigger_date = entry["trigger_date"]
    target_price = target["price"]

    candles_after_trigger = data[
        data.index > trigger_date
    ]

    for _, candle in candles_after_trigger.iterrows():

        candle_high = float(
            candle["High"]
        )

        if candle_high >= target_price:
            return "Target Reached"

    return "Triggered, Target Not Reached"    

# ============================================================
# GRADE
# ============================================================

def grade_setup(
    current_price,
    avg_volume,
    setup,
    entry,
    target,
    support,
    resistance
):

    score = 0
    reasons = []

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price_pass = (
        MIN_PRICE
        <= current_price
        <= MAX_PRICE
    )

    if price_pass:

        score += 1
        reasons.append(
            "Price filter passed"
        )

    else:

        reasons.append(
            "Price filter failed"
        )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    volume_pass = (
        avg_volume >= MIN_AVG_VOLUME
    )

    if volume_pass:

        score += 1
        reasons.append(
            "Volume filter passed"
        )

    else:

        reasons.append(
            "Volume filter failed"
        )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if setup is not None:

        score += 2

        reasons.append(
            "Daily MACD setup detected"
        )

    else:

        reasons.append(
            "No valid daily MACD setup"
        )

    # --------------------------------------------------------
    # ENTRY
    # --------------------------------------------------------

    if entry is not None:

        if entry["triggered_today"]:

            score += 1

            reasons.append(
                "INITIAL BREAK TODAY - valid entry opportunity"
            )

        elif entry["triggered"]:

            reasons.append(
                "ENTRY EXPIRED - initial break already occurred"
            )

        else:

            score += 1

            reasons.append(
                "Entry trigger is waiting for initial break"
            )

    # --------------------------------------------------------
    # TARGET
    # --------------------------------------------------------

    target_upside = None

    if target is not None and entry is not None:

        entry_price = entry[
            "entry_price"
        ]

        target_upside = (
            target ["price"] - entry_price
        ) / entry_price

        if target_upside >= MIN_TARGET_UPSIDE:

            score += 2

            reasons.append(
                f"Target provides "
                f"{target_upside * 100:.2f}% upside"
            )

        else:

            reasons.append(
                "Target upside is too small"
            )

    else:

        reasons.append(
            "No valid upside target"
        )

    # --------------------------------------------------------
    # SUPPORT
    # --------------------------------------------------------

    if support is not None and entry is not None:

        entry_price = entry[
            "entry_price"
        ]

        support_distance = (
            entry_price - support["price"]
        ) / entry_price

        if support_distance <= SUPPORT_DISTANCE:

            score += 1

            reasons.append(
                "Entry is near daily support"
            )

    # --------------------------------------------------------
    # RESISTANCE
    # --------------------------------------------------------

    if (
        resistance is not None
        and entry is not None
    ):

        if resistance["price"] > entry["entry_price"]:

            score += 1

            reasons.append(
                f"Daily resistance:    ${resistance['price']:.4f}"
            )

    # --------------------------------------------------------
    # FINAL GRADE
    # --------------------------------------------------------

    if (
        price_pass
        and volume_pass
        and setup is not None
        and entry is not None
        and (
            not entry["triggered"]
            or entry["triggered_today"]
        )
        and target is not None
        and target_upside is not None
        and target_upside >= MIN_TARGET_UPSIDE
    ):

        if score >= 8:

            grade = "A+"

        elif score >= 6:

            grade = "A"

        elif score >= 4:

            grade = "B"

        else:

            grade = "NO TRADE"

    else:

        grade = "NO TRADE"

    return grade, score, reasons


# ============================================================
# ANALYZE ONE STOCK
# ============================================================

def analyze_stock(symbol):

    print()
    print("=" * 70)
    print(f"DAILY ANALYSIS: {symbol}")
    print("=" * 70)

    data = get_daily_data(symbol)

    if data is None:

        print("No daily data available.")
        return None

    current_price = float(
        data["Close"].iloc[-1]
    )

    avg_volume = float(
        data["Volume"].tail(60).mean()
    )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    setup = find_macd_setup(data)

    # --------------------------------------------------------
    # SUPPORT / RESISTANCE
    # --------------------------------------------------------

    (
        support,
        resistance,
        swing_highs,
        swing_lows
    ) = find_support_resistance(data)

    # --------------------------------------------------------
    # ENTRY
    # --------------------------------------------------------

    entry = calculate_entry(
        data,
        setup
    )
    target = None

    if entry is not None:

        target = calculate_target(
            entry["entry_price"],
            swing_highs
        )

    trade_status = calculate_trade_status(
        data,
        entry,
        target,
        entry["entry_price"] if entry else None,
        swing_highs
    )

    # --------------------------------------------------------
    # TARGET
    # --------------------------------------------------------

    target = None

    if entry is not None:

        target = calculate_target(
            entry["entry_price"],
            swing_highs
        )

    # --------------------------------------------------------
    # GRADE
    # --------------------------------------------------------

    (
        grade,
        score,
        reasons
    ) = grade_setup(
        current_price,
        avg_volume,
        setup,
        entry,
        target,
        support,
        resistance
    )

    # ========================================================
    # DISPLAY
    # ========================================================

    print(
        f"Current Price:       ${current_price:.2f}"
    )

    print(
        f"Average Daily Vol:   {avg_volume:,.0f}"
    )

    print(
        "Chart Timeframe:     DAILY"
    )

    print()

    print(
        f"Price Filter:        "
        f"{'PASS' if MIN_PRICE <= current_price <= MAX_PRICE else 'FAIL'}"
    )

    print(
        f"Volume Filter:       "
        f"{'PASS' if avg_volume >= MIN_AVG_VOLUME else 'FAIL'}"
    )

    # --------------------------------------------------------
    # SUPPORT
    # --------------------------------------------------------

    print()

    if support is not None:

        print(
            f"Daily Support:       ${support['price']: .4f}"
        )

    else:

        print(
            "Daily Support:       N/A"
        )

    # --------------------------------------------------------
    # RESISTANCE
    # --------------------------------------------------------

    if resistance is not None:

        print(
            f"Daily Resistance:    ${resistance['price']: .4f}"
        )

    else:

        print(
            "Daily Resistance:    N/A"
        )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    print()

    if setup is not None:

        print(
            "DAILY MACD SETUP:    FOUND"
        )

        print(
            f"Setup Date:          "
            f"{setup['date']}"
        )

        print(
            f"Setup Candle High:   "
            f"${setup['high']:.4f}"
        )

        print(
            f"Setup Candle Low:    "
            f"${setup['low']:.4f}"
        )

        print(
            f"MACD:                "
            f"{setup['macd']:.5f}"
        )

        print(
            f"Signal:              "
            f"{setup['signal']:.5f}"
        )

        print(
            f"Histogram:           "
            f"{setup['histogram']:.5f}"
        )

    else:

        print(
            "DAILY MACD SETUP:    NONE"
        )

    # --------------------------------------------------------
    # ENTRY
    # --------------------------------------------------------

    print()

    if entry is not None:

        print(
            f"Daily Entry Trigger: "
            f"${entry['entry_price']:.4f}"
        )

        if entry["triggered_today"]:

            print(
                "Trigger Status:      INITIAL BREAK TODAY"
            )

            print(
                f"Trigger Date:        "
                f"{entry['trigger_date']}"
            )

        elif entry["triggered"]:

            print(
                "Trigger Status:      EXPIRED"
            )

            print(
                f"Trigger Date:        "
                f"{entry['trigger_date']}"
            )

        else:

            print(
                "Trigger Status:      WAITING"
            )

    else:

        print(
            "Daily Entry Trigger: N/A"
        )

    # --------------------------------------------------------
    # TARGET
    # --------------------------------------------------------

    print()

    if (
        target is not None
        and entry is not None
    ):

        entry_price = entry[
            "entry_price"
        ]

        upside = (
            target["price"] - entry_price
        ) / entry_price

        print(
            f"Daily Target:        ${target['price']: .4f}"
        )
        print(
            f"Target Level Source Date:         {target['date']}"
        )
        print(
            f"Potential Upside:    "
            f"{upside * 100:.2f}%"
        )

        print(
            f"Trade Status:        {trade_status}"
        )
    else:

        print(
            "Daily Target:        NO VALID TARGET"
        )

    # --------------------------------------------------------
    # GRADE
    # --------------------------------------------------------

    print()

    print("-" * 70)

    print(
        f"TRADEPILOTAI GRADE:   {grade}"
    )

    print(
        f"SETUP SCORE:          {score}"
    )

    print("-" * 70)

    for reason in reasons:

        print(
            f"• {reason}"
        )

    return {
        "symbol": symbol,
        "price": current_price,
        "volume": avg_volume,
        "support": support,
        "resistance": resistance,
        "setup": setup,
        "entry": entry,
        "target": target,
        "grade": grade,
        "score": score,
        "trade_status": trade_status
    }


# ============================================================
# RUN SCANNER
# ============================================================
def detect_scan_changes(results):

    if not HISTORY_FILE.exists():
        return []

    with open(
        HISTORY_FILE,
        mode="r",
        newline=""
    ) as csvfile:

        rows = list(
            csv.DictReader(csvfile)
        )

    if not rows:
        return []

    # Find the most recent completed scan in history
    latest_timestamp = max(
        row["timestamp"]
        for row in rows
    )

    # Keep only records from that most recent scan
    latest_rows = [
        row
        for row in rows
        if row["timestamp"] == latest_timestamp
    ]

    # Fast lookup by ticker
    previous_by_symbol = {
        row["symbol"]: row
        for row in latest_rows
    }

    changes = []

    for result in results:

        symbol = result["symbol"]

        previous = previous_by_symbol.get(
            symbol
        )

        if previous is None:
            changes.append({
                "symbol": symbol,
                "change_type": "NEW SYMBOL",
                "previous_grade": None,
                "current_grade": result["grade"],
                "previous_trade_status": None,
                "current_trade_status": result["trade_status"]
            })

            continue

        previous_grade = previous.get(
            "grade",
            ""
        )

        previous_trade_status = previous.get(
            "trade_status",
            ""
        )

        current_grade = result.get(
            "grade",
            ""
        )

        current_trade_status = result.get(
            "trade_status",
            ""
        )

    if current_grade != previous_grade:

        changes.append({
            "symbol": symbol,
            "change_type": "GRADE CHANGE",
            "previous_grade": previous_grade,
            "current_grade": current_grade,
            "previous_trade_status": previous_trade_status,
            "current_trade_status": current_trade_status
        })

    elif current_trade_status != previous_trade_status:

        changes.append({
            "symbol": symbol,
            "change_type": "TRADE STATUS CHANGE",
            "previous_grade": previous_grade,
            "current_grade": current_grade,
            "previous_trade_status": previous_trade_status,
            "current_trade_status": current_trade_status
        })

        return changes

    

def save_scan_history(results):

    # Create the directory if it doesn't exist
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Check if the file exists to determine if we need to write headers
    file_exists = HISTORY_FILE.exists()

    with open(HISTORY_FILE, mode='a', newline='') as csvfile:
        fieldnames = [
            'timestamp', 'symbol', 'price', 'volume', 'support',
            'resistance', 'setup', 'entry', 'target', 'grade',
            'score', 'trade_status'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        # Write headers only if the file didn't exist before
        if not file_exists:
            writer.writeheader()

        for result in results:
            writer.writerow({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'symbol': result['symbol'],
                'price': result['price'],
                'volume': result['volume'],
                'support': result['support']['price'] if result['support'] else None,
                'resistance': result['resistance']['price'] if result['resistance'] else None,
                'setup': result['setup']['setup_type'] if result['setup'] else None,
                'entry': result['entry']['entry_price'] if result['entry'] else None,
                'target': result['target']['price'] if result['target'] else None,
                'grade': result['grade'],
                'score': result['score'],
                'trade_status': result['trade_status']
            })
def generate_daily_report(results, changes):
    
    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    report_date = datetime.now().strftime(
        "%Y-%m-%d"
    )

    report_file = REPORTS_DIR / (
        f"daily_report_{report_date}.txt"
    )

    with open(
        report_file,
        "w"
        ) as file:

        file.write(
            "TRADEPILOTAI DAILY REPORT\n"
        )

        file.write(
            "=" * 60 + "\n"
        )

        file.write(
            f"Date: {report_date}\n\n"
        )
        file.write("SCAN RESULTS\n")
        file.write("-" * 60 + "\n")

        for result in results:

            file.write(
            f"{result['symbol']}: "
            f"Grade {result['grade']}\n"
            )

        file.write("\n")

        waiting = []

        for result in results:

            entry = result.get("entry")
            target = result.get("target")
            grade = result.get("grade")

            if (
                entry is not None
                and target is not None
                and not entry["triggered"]
                and grade in ["A+", "A", "B"]
            ):

                upside = (
                    target["price"] - entry["entry_price"]
                ) / entry["entry_price"]

                waiting.append({
                    "symbol": result["symbol"],
                    "entry": entry["entry_price"],
                    "target": target["price"],
                    "upside": upside
                })

        if waiting:

            waiting.sort(
                key=lambda item: item["upside"],
                reverse=True
            )

            top_watch = waiting[0]

            file.write("TOP WATCH\n")
            file.write("-" * 60 + "\n")

            file.write(
                f"{top_watch['symbol']} - "
                f"Entry: ${top_watch['entry']:.4f} "
                f"-> Target: ${top_watch['target']:.4f} "
                f"- Upside: {top_watch['upside'] * 100:.2f}%\n\n"
            )   

        file.write("WAITING FOR INITIAL BREAK\n")
        file.write("-" * 60 + "\n")

        if waiting:
            for item in waiting:
                file.write(
                    f"{item['symbol']} - "
                    f"Entry: ${item['entry']:.4f} "
                    f"-> Target: ${item['target']:.4f} "
                    f"- Upside: {item['upside'] * 100:.2f}%\n"
                )
        else:
            file.write("None\n")

        file.write("\n")
        file.write("SCAN CHANGES\n")
        file.write("-" * 60 + "\n")

        if changes:
            for change in changes:
                file.write(
                    f"{change['symbol']}: "
                    f"{change['change_type']}\n"
                )

                file.write(
                    f"  Grade: "
                    f"{change['previous_grade']} "
                    f"-> {change['current_grade']}\n"
                )

                file.write(
                    f"  Status: "
                    f"{change['previous_trade_status']} "
                    f"-> {change['current_trade_status']}\n"
                )
        else:
            file.write("None\n")

        file.write("\n")

        file.write("TRIGGERED TODAY / ENTRY ALERTS\n")
        file.write("-" * 60 + "\n")

        triggered_found = False

        for result in results:

            entry = result.get("entry")
            target = result.get("target")

            if (
                entry is not None
                and entry.get("triggered_today")
            ):

                triggered_found = True

                file.write(
                    f"{result['symbol']} - "
                    f"Entry: ${entry['entry_price']:.4f}"
                )

                if target is not None:
                    file.write(
                        f" -> Target: ${target['price']:.4f}"
                    )

                file.write("\n")

        if not triggered_found:
            file.write("None\n")

        file.write("\n")    
    return report_file

def save_broker_queue(order_previews):

    BROKER_QUEUE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        BROKER_QUEUE_FILE,
        "w"
    ) as file:

        json.dump(
            order_previews,
            file,
            indent=4
        )

def run_scanner():

    broker = RobinhoodBroker()
    broker.connect()

    broker_status = broker.get_account_status()

    if TEST_MODE:
        print("TEST MODE ENABLED - no real orders can be submitted.")

    print()
    print("=" * 70)
    print("              TRADEPILOTAI VERSION 3")
    print("                 DAILY CHART ONLY")
    print("=" * 70)

    print()
    print(
        f"Price Range:         "
        f"${MIN_PRICE:.2f} - ${MAX_PRICE:.2f}"
    )

    print(
        f"Minimum Daily Vol:   "
        f"{MIN_AVG_VOLUME:,}"
    )

    print(
        "Chart Timeframe:     DAILY"
    )

    print(
        f"MACD:                "
        f"{MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}"
    )

    print(
        f"Minimum Target:      "
        f"{MIN_TARGET_UPSIDE * 100:.1f}%"
    )

    print()

    results = []
    order_previews = []

    if TEST_MODE:

        test_preview = broker.preview_order(
            "TEST",
            1
        )

        test_preview = broker.approve_preview(
            test_preview,
            approved=False
        )

        order_previews.append(
            test_preview
        )

    for symbol in WATCHLIST:

        result = analyze_stock(symbol)

        if result is not None:
 
            results.append(result)

    changes = detect_scan_changes(results)

    save_scan_history(results)

    report_file = generate_daily_report(
        results, 
        changes
    )

    
   

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()
    print()
    print("=" * 70)
    print("                    FINAL SUMMARY")
    print("=" * 70)

    grades = {
        "A+": [],
        "A": [],
        "B": [],
        "NO TRADE": []
    }
    
    waiting = []
    triggered_today = []
    triggered_not_reached = []
    entry_alerts = []


    for result in results:

        grade = result["grade"]

        entry = result["entry"]

        if entry is not None:

            if entry["triggered_today"]:

                triggered_today.append(
                    result["symbol"]
                )
                target = result["target"]
                entry_alerts.append(
                    f"{result['symbol']} ENTRY TRIGGERED  "
                    f"@ ${entry['entry_price']:.4f}"
                    f"-> TARGET: ${target['price']:.4f}"
                )
                preview = broker.preview_order(
                    result["symbol"],
                    1
                )
                preview = broker.approve_preview(
                    preview,
                    approved=False
                )
                order_previews.append(preview)

                review_result = asyncio.run(
                    review_triggered_order(
                        result["symbol"],
                        quantity=1,
                        triggered_today=True
                    )
                )
                handoff = broker.build_execution_handoff(
                    preview,
                    test_mode=TEST_MODE,
                )
                preview["handoff_status"] = handoff["status"]
                execution_ticket = build_execution_ticket(preview)
                preview["execution_ticket_status"] = (
                    "READY" if execution_ticket is not None else "BLOCKED"
                )

            elif (
                not entry["triggered"]
                and grade in ["A+", "A", "B"]
            ):

                target = result["target"]

                if target is not None:
                    upside = (
                        target["price"] - entry["entry_price"]
                    ) / entry["entry_price"]

                    waiting.append(
                        {
                            "symbol": result["symbol"],
                            "entry": entry["entry_price"],
                            "target": target["price"],
                            "upside": upside
                        }
                    )

        if grade in grades:

            grades[grade].append(
                result["symbol"]
            )
    save_broker_queue(order_previews)


    for grade in [
        "A+",
        "A",
        "B",
        "NO TRADE"
    ]:

        stocks = grades[grade]

        if stocks:

            print(
                f"{grade}: "
                f"{', '.join(stocks)}"
            )

        else:

            print(
                f"{grade}: None"
            )
    print("Waiting for Initial Break: ")

    if waiting:
        waiting.sort(
            key=lambda item: item["upside"],
            reverse=True
        )

        for item in waiting:
            print(
                f"{item['symbol']} - "
                f"Entry: ${item['entry']:.4f}, "
                f"Target: ${item['target']:.4f}, "
                f"Upside: {item['upside'] * 100:.2f}%"
            )
    else:

        print("None")
    print()
    if waiting:

        top_waiting = waiting[0]

        print(
            "TOP WATCH: "
            f"{top_waiting['symbol']} "
            f"- Entry: ${top_waiting['entry']:.4f}, "
            f"-> Target: ${top_waiting['target']:.4f}, "
            f"Upside: {top_waiting['upside'] * 100:.2f}%"
        )
    else:

        print("TOP WATCH: None")    
    
    print(
         "Triggered Today: "
         f"{', '.join(triggered_today) if triggered_today else 'None'}"
    )
    print(
        "Triggered, Target Not Reached: "
    )
    if triggered_not_reached:
        for symbol in triggered_not_reached:
            print(f" - {symbol}")
    else:
        print("None")
    print()

    print("Entry Alerts: ")

    if entry_alerts:
        for alert in entry_alerts:
            print("=" * 60)
            print(f" ENTRY ALERT: {alert}")
            print("=" * 60)
    else:

        print("None")
    print()

    print(
        "BROKER STATUS: "
        f"{'CONNECTED' if broker_status['connected'] else 'DISCONNECTED'}"
    )
    print("ORDER PREVIEWS:")

    if order_previews:
        for preview in order_previews:

            block_reason = broker.get_submission_block_reason(
                preview,
                test_mode=TEST_MODE
            )
            print(
                f"  - {preview['symbol']} "
                f"Qty: {preview['quantity']} "
                f"Type: {preview['order_type']} "
                f"Status: {preview['status']} "
                f"Block Reason: {block_reason} "
                f" Handoff: {preview.get('handoff_status', 'N/A')}"
                f" Ticket: {preview.get('execution_ticket_status', 'N/A')}"
            )
    else:
        print("  None")
    print()

    print("SCAN CHANGES:")

    if changes:

        for change in changes:

            print(
            f"  - {change['symbol']}: "
            f"{change['change_type']}"
            )

            print(
            f"    Grade: "
            f"{change['previous_grade']} "
            f"-> {change['current_grade']}"
            )

        print(
            f"    Status: "
            f"{change['previous_trade_status']} "
            f"-> {change['current_trade_status']}"
        )

    else:

             print("  None")

    print()

    print("=" * 70)
    print("DAILY SCAN COMPLETE")
    print("=" * 70)

    print()






# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    run_scanner()