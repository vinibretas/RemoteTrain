# pico_ook_tx.py  –  minimal RF-burst encoder
#
# Hardware assumption:
#   • Pin 15 drives the ASK / OOK RF-transmitter enable (active-HIGH).
#   • The external circuit expects:
#       – one long LOW “sync gap”  (default 30 ms)
#       – N short 50 %-duty pulses at a specific pulse-rate “frequency”
#         (N = 1-8 selects which of the eight outputs will latch).
#
# Usage example:
#     send_command(cmd=3, frequency=250)  # 3-pulse frame @250 Hz PRF
#
from machine import Pin
import utime

_TX = Pin(15, Pin.OUT, value=0)   # transmitter key pin (starts LOW)

def send_command(
    cmd: int,
    frequency: float,
    sync_gap_ms: int = 30,
    pin: Pin = _TX) -> None:
    """
    Transmit a pulse-count frame to the discrete decoder.

    Args:
        cmd        – integer 1-8  (number of pulses after the gap)
        frequency  – pulse repetition frequency in hertz
                     (must match the board’s duty-cycle window)
        sync_gap_ms – duration of the long LOW gap that marks frame start
        pin        – (optional) GPIO pin already configured as cmd
    """
    if not (1 <= cmd <= 8):
        raise ValueError("cmd must be 1-8")

    if frequency <= 0:
        raise ValueError("frequency must be > 0 Hz")

    period_us = int(1_000_000 / frequency)
    half_us   = period_us // 2          # 50 % duty for simplicity

    # ----- 1. long LOW gap (sync) -----
    pin.value(0)
    utime.sleep_ms(sync_gap_ms)

    # ----- 2. send N pulses ----------
    for _ in range(cmd):
        pin.value(1)
        utime.sleep_us(half_us)
        pin.value(0)
        utime.sleep_us(half_us)
