"""
Core BLE state machine ported from celesWuff/waterctl/src/bluetooth.ts

Uses the `bleak` library for cross-platform Bluetooth LE access.
This module is used by both the Windows and Android (if bleak is available)
frontends. The Web frontend uses the browser's Web Bluetooth API instead.

Usage example (asyncio):

    from core.bluetooth import WaterController, Stage

    async def main():
        ctrl = WaterController()
        ctrl.on_stage_change = lambda s: print("Stage:", s)
        ctrl.on_error = lambda msg, fatal: print("Error:", msg, "fatal:", fatal)

        device = await ctrl.scan()          # show device-picker
        await ctrl.connect(device)          # connect + start session
        input("Press Enter to stop...")
        await ctrl.end()                    # end session gracefully
"""

import asyncio
import logging
from enum import Enum
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from .payloads import (
    BA_ACK,
    END_EPILOGUE,
    END_PROLOGUE,
    OFFLINEBOMB_FIX,
    RXD_UUID,
    SERVICE_UUID,
    START_PROLOGUE,
    TXD_UUID,
)
from .solvers import make_start_epilogue, make_unlock_response

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15


class Stage(str, Enum):
    STANDBY = "standby"   # not connected
    PENDING = "pending"   # connected, handshaking
    ACTIVE = "active"     # session is live
    ERROR = "error"


def _normalize_payload(raw: bytes) -> Optional[bytes]:
    """Normalise incomplete packets produced by buggy firmware.

    The firmware may omit the first one or two 0xFD bytes, and occasionally
    sends noise AT-commands or single-byte packets.  Returns None when the
    packet should be silently discarded.
    """
    p = bytearray(raw)

    # AT+STAS? noise from firmware bug — discard
    if len(p) >= 3 and p[0] == 0x41 and p[1] == 0x54 and p[2] == 0x2B:
        return None

    # Must start with 0xFD or 0x09
    if p[0] not in (0xFD, 0x09):
        raise ValueError(f"Unknown RXD data: {p.hex()}")

    # [0xFD, 0x09, ...] -> [0xFD, 0xFD, 0x09, ...]
    if len(p) >= 2 and p[1] == 0x09:
        p = bytearray([0xFD]) + p

    # [0x09, ...] -> [0xFD, 0xFD, 0x09, ...]
    if p[0] == 0x09:
        p = bytearray([0xFD, 0xFD]) + p

    # Single 0xFD byte — discard
    if len(p) < 4:
        return None

    return bytes(p)


class WaterController:
    """Async state machine that manages one BLE water-dispenser session."""

    def __init__(self) -> None:
        self._client: Optional[BleakClient] = None
        self._device: Optional[BLEDevice] = None
        self._stage: Stage = Stage.STANDBY
        self._is_started: bool = False
        self._pending_epilogue_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None

        # Public callbacks — set before calling connect()
        self.on_stage_change: Optional[Callable[[Stage], None]] = None
        self.on_error: Optional[Callable[[str, bool], None]] = None  # (message, is_fatal)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan(self) -> BLEDevice:
        """Scan for BLE devices and return the first one that matches.

        In a real GUI you would show a list; here we return whichever device
        advertises the water-dispenser service UUID first.
        """
        logger.info("Scanning for hot water controller…")
        device = await BleakScanner.find_device_by_filter(
            lambda d, _adv: True,  # accept any; GUI layer should filter
            timeout=10.0,
        )
        if device is None:
            raise RuntimeError("No BLE device found")
        return device

    async def scan_all(self, timeout: float = 10.0) -> list[BLEDevice]:
        """Return all discovered BLE devices (for display in a picker)."""
        return await BleakScanner.discover(timeout=timeout)

    async def connect(self, device: BLEDevice) -> None:
        """Connect to *device* and start the water session."""
        self._device = device
        self._set_stage(Stage.PENDING)

        self._client = BleakClient(device, disconnected_callback=self._on_disconnected)
        await self._client.connect()

        await self._client.start_notify(RXD_UUID, self._handle_rxd)
        await self._txd_write(START_PROLOGUE)
        self._arm_timeout()

    async def end(self) -> None:
        """Gracefully end an active session."""
        if not self._client or not self._client.is_connected:
            return
        try:
            await self._txd_write(END_PROLOGUE)
            self._arm_timeout()
        except Exception as exc:
            await self._handle_error(exc)

    async def disconnect(self) -> None:
        """Disconnect immediately, resetting all state."""
        self._cancel_pending_tasks()
        self._is_started = False
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._set_stage(Stage.STANDBY)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_stage(self, stage: Stage) -> None:
        self._stage = stage
        if self.on_stage_change:
            self.on_stage_change(stage)

    async def _txd_write(self, data: bytes) -> None:
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("Not connected")
        logger.debug("TXD: %s", data.hex().upper())
        await self._client.write_gatt_char(TXD_UUID, data, response=False)

    def _arm_timeout(self) -> None:
        if self._timeout_task is None or self._timeout_task.done():
            self._timeout_task = asyncio.create_task(self._timeout_handler())

    async def _timeout_handler(self) -> None:
        await asyncio.sleep(TIMEOUT_SECONDS)
        await self._handle_error(RuntimeError("WATERCTL INTERNAL Operation timed out"))

    def _cancel_pending_tasks(self) -> None:
        for task in (self._pending_epilogue_task, self._timeout_task):
            if task and not task.done():
                task.cancel()
        self._pending_epilogue_task = None
        self._timeout_task = None

    def _on_disconnected(self, _client: BleakClient) -> None:
        logger.info("Device disconnected")
        self._cancel_pending_tasks()
        self._is_started = False
        self._set_stage(Stage.STANDBY)

    async def _handle_error(self, error: Exception) -> None:
        msg = str(error)
        logger.error("BLE error: %s", msg)

        is_fatal = True
        if "Unknown RXD data" in msg:
            is_fatal = False
        elif "Operation timed out" in msg:
            is_fatal = False

        if self.on_error:
            self.on_error(msg, is_fatal)

        if is_fatal:
            await self.disconnect()

    # ------------------------------------------------------------------
    # RXD notification handler (the heart of the protocol)
    # ------------------------------------------------------------------

    async def _handle_rxd(self, _sender: int, raw: bytearray) -> None:
        logger.debug("RXD: %s", raw.hex().upper())
        try:
            payload = _normalize_payload(bytes(raw))
            if payload is None:
                return

            d_type = payload[3]

            if d_type in (0xB0, 0xB1):
                # Start prologue OK.  New firmware will follow with AE after 500 ms.
                # Schedule the start-epilogue with a 500 ms delay; if AE arrives
                # first, the scheduled task is cancelled.
                self._cancel_pending_tasks()

                async def _delayed_start_epilogue() -> None:
                    await asyncio.sleep(0.5)
                    await self._txd_write(make_start_epilogue(self._device.name or ""))

                self._pending_epilogue_task = asyncio.create_task(_delayed_start_epilogue())

            elif d_type == 0xAE:
                # Key-authentication challenge (new firmware)
                self._cancel_pending_tasks()
                response = make_unlock_response(payload, self._device.name or "")
                await self._txd_write(response)

            elif d_type == 0xAF:
                sub = payload[5]
                if sub == 0x55:
                    # Key auth OK → send start epilogue with auth flag
                    await self._txd_write(make_start_epilogue(self._device.name or "", True))
                elif sub in (0x01, 0x02, 0x04):
                    raise RuntimeError("WATERCTL INTERNAL Bad key")
                else:
                    await self._txd_write(make_start_epilogue(self._device.name or "", True))
                    raise RuntimeError("WATERCTL INTERNAL Unknown RXD data")

            elif d_type == 0xB2:
                # Session started
                self._cancel_pending_tasks()
                self._is_started = True
                self._set_stage(Stage.ACTIVE)

            elif d_type == 0xB3:
                # End prologue ACK → send end epilogue then disconnect
                await self._txd_write(END_EPILOGUE)
                await self.disconnect()

            elif d_type in (0xAA, 0xB5, 0xB8):
                # Telemetry / temperature / unknown — no response needed
                pass

            elif d_type == 0xBA:
                # User-info upload request → fake the ACK
                await self._txd_write(BA_ACK)

            elif d_type == 0xBC:
                # Offline-bomb artefact
                await self._txd_write(OFFLINEBOMB_FIX)

            elif d_type == 0xC8:
                raise RuntimeError("WATERCTL INTERNAL Refused")

            else:
                raise RuntimeError("WATERCTL INTERNAL Unknown RXD data")

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await self._handle_error(exc)
