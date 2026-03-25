"""
Payload builders ported from celesWuff/waterctl/src/solvers.ts

The key-derivation step (makeUnlockKey) originally runs inside deputy.wasm.
Place deputy.wasm in the same directory as this file, or set the
DEPUTY_WASM environment variable to its path.

deputy.wasm exports:
  makeKey(b0, b1, b2, b3) -> void   (result stored at memory[524] as uint32, big-endian)
  memory                  -> WebAssembly.Memory

Obtain deputy.wasm from the original project:
  https://github.com/celesWuff/waterctl/blob/2.x/src/deputy.wasm
"""

import os
import random
import struct
from datetime import datetime
from pathlib import Path

import pytz

from .algorithms import crc16_changgong, crc16_cgaeaf

# Resolve deputy.wasm path
_WASM_PATH = Path(os.environ.get("DEPUTY_WASM", Path(__file__).parent / "deputy.wasm"))


def _dec_as_hex(n: int) -> int:
    """Convert decimal digits to their hex encoding: 42 -> 0x42."""
    if n <= 0:
        return 0
    return (n % 10) | (_dec_as_hex(n // 10) << 4)


def _make_random_user_id() -> bytes:
    """Return 2 bytes: a random user-ID in the device's BCD-ish encoding."""
    random_id = random.randint(1, 9999)
    high = random_id >> 8
    low = random_id & 0xFF
    return bytes([_dec_as_hex(high), _dec_as_hex(low)])


def _make_datetime_array() -> bytes:
    """Return 6 bytes encoding the current Shanghai time as BCD-ish values.

    Example: 2023-01-11 12:34:56  →  [0x23, 0x01, 0x11, 0x12, 0x34, 0x56]
    """
    tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(tz)
    parts = [now.year % 100, now.month, now.day, now.hour, now.minute, now.second]
    return bytes([_dec_as_hex(p) for p in parts])


def _make_unlock_key(data: bytes) -> bytes:
    """Run deputy.wasm to compute the 4-byte unlock key from *data* (2-byte nonce + 2-byte MAC).

    Raises RuntimeError if deputy.wasm is not found or wasmtime is not installed.
    """
    if not _WASM_PATH.exists():
        raise RuntimeError(
            f"deputy.wasm not found at {_WASM_PATH}. "
            "Download it from https://github.com/celesWuff/waterctl/blob/2.x/src/deputy.wasm "
            "and place it next to core/solvers.py, or set the DEPUTY_WASM env-var."
        )

    try:
        import wasmtime
    except ImportError as exc:
        raise RuntimeError("wasmtime-py is required for key derivation: pip install wasmtime") from exc

    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    module = wasmtime.Module.from_file(engine, str(_WASM_PATH))
    instance = wasmtime.Instance(store, module, [])
    exports = instance.exports(store)

    make_key = exports["makeKey"]
    memory: wasmtime.Memory = exports["memory"]

    if len(data) != 4:
        raise ValueError("makeUnlockKey expects exactly 4 bytes")

    make_key(store, int(data[0]), int(data[1]), int(data[2]), int(data[3]))

    # Read the result uint32 at word offset 524 (byte offset 2096), big-endian
    mem_bytes = bytes(memory.data_ptr(store)[2096:2100])
    key_int = struct.unpack(">I", mem_bytes)[0]
    return bytes([(key_int >> (8 * (3 - i))) & 0xFF for i in range(4)])


def make_unlock_response(unlock_request: bytes, device_name: str) -> bytes:
    """Build the AF reply to an AE unlock challenge.

    *unlock_request* is the full RXD payload received from the device.
    """
    unknown_byte = unlock_request[5]
    nonce_bytes = unlock_request[6:8]
    mac = unlock_request[8:10]

    nonce = (nonce_bytes[0] << 8) | nonce_bytes[1]
    if nonce == 0xFFFF:
        # Bug-for-bug compatible with the original firmware behaviour
        new_nonce_bytes = bytes([0x01, 0x00])
    else:
        new_nonce = nonce + 1
        new_nonce_bytes = bytes([(new_nonce >> 8) & 0xFF, new_nonce & 0xFF])

    raw_key = _make_unlock_key(bytes([*nonce_bytes, *mac]))

    mask = [ord(c) - 0x30 for c in device_name[-4:]]
    key = bytes([raw_key[i] ^ mask[i] for i in range(4)])

    checksum_input = bytes(
        [
            unknown_byte,
            *new_nonce_bytes,
            *key,
            0xFE,
            0x87,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )

    checksum = crc16_cgaeaf(checksum_input)

    return bytes([0xFE, 0xFE, 0x09, 0xAF, checksum, *checksum_input])


def make_start_epilogue(device_name: str, is_key_auth_present: bool = False) -> bytes:
    """Build the B2 start-epilogue payload that officially begins a session."""
    checksum = crc16_changgong(device_name[-5:])
    mn = 0x0B if is_key_auth_present else 0xFF  # magic number
    ri = _make_random_user_id()
    dt = _make_datetime_array()
    return bytes(
        [
            0xFE,
            0xFE,
            0x09,
            0xB2,
            0x01,
            checksum & 0xFF,
            checksum >> 8,
            mn,
            0x00,
            *ri,
            *dt,
            0x0F,
            0x27,
            0x00,
        ]
    )
