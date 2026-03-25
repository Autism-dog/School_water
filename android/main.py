"""
Android APK — Kivy native UI + pyjnius (Android BLE) for water dispenser control.

Build with buildozer:
    cd android/
    buildozer android debug

BLE is accessed through Android's native BluetoothGatt API via pyjnius.
The protocol implementation mirrors core/bluetooth.py.
"""

import asyncio
import threading
import random
import struct
from datetime import datetime
from functools import partial

import pytz
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

# ── Colour palette ──
PINK_DEEP   = (0.906, 0.329, 0.502, 1)
PINK_MAIN   = (0.957, 0.561, 0.694, 1)
PINK_LIGHT  = (0.988, 0.894, 0.925, 1)
PINK_PALE   = (1,     0.941, 0.961, 1)
WHITE       = (1, 1, 1, 1)
TEXT_DARK   = (0.353, 0.227, 0.290, 1)

# ────────────────────────────────────────────────────────────────────────────
# Protocol helpers (mirrors core/algorithms.py + core/solvers.py)
# ────────────────────────────────────────────────────────────────────────────

def _dec_as_hex(n: int) -> int:
    if n <= 0:
        return 0
    return (n % 10) | (_dec_as_hex(n // 10) << 4)


def crc16_changgong(s: str) -> int:
    crc = 0x1017
    for c in s:
        crc ^= ord(c)
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc16_cgaeaf(data: bytes) -> int:
    crc = 0x6A1F
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return (crc ^ 0x75) & 0xFF


def make_start_epilogue(device_name: str, key_auth: bool = False) -> bytes:
    checksum = crc16_changgong(device_name[-5:])
    mn = 0x0B if key_auth else 0xFF
    tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(tz)
    parts = [now.year % 100, now.month, now.day, now.hour, now.minute, now.second]
    dt = bytes([_dec_as_hex(p) for p in parts])
    rand_id = random.randint(1, 9999)
    ri = bytes([_dec_as_hex(rand_id >> 8), _dec_as_hex(rand_id & 0xFF)])
    return bytes([0xFE, 0xFE, 0x09, 0xB2, 0x01, checksum & 0xFF, checksum >> 8, mn,
                  0x00, *ri, *dt, 0x0F, 0x27, 0x00])


START_PROLOGUE  = bytes([0xFE, 0xFE, 0x09, 0xB0, 0x01, 0x01, 0x00, 0x00])
END_PROLOGUE    = bytes([0xFE, 0xFE, 0x09, 0xB3, 0x00, 0x00])
END_EPILOGUE    = bytes([0xFE, 0xFE, 0x09, 0xB4, 0x00, 0x00])
OFFLINEBOMB_FIX = bytes([0xFE, 0xFE, 0x09, 0xBC, 0x00, 0x00])
BA_ACK          = bytes([0xFE, 0xFE, 0x09, 0xBA, 0x00, 0x00])

SERVICE_UUID = "0000f1f0-0000-1000-8000-00805f9b34fb"
TXD_UUID     = "0000f1f1-0000-1000-8000-00805f9b34fb"
RXD_UUID     = "0000f1f2-0000-1000-8000-00805f9b34fb"

# ────────────────────────────────────────────────────────────────────────────
# Android BLE wrapper (pyjnius — only available on Android at runtime)
# ────────────────────────────────────────────────────────────────────────────

class AndroidBLE:
    """Thin wrapper around Android BluetoothGatt / BluetoothLeScanner via pyjnius."""

    def __init__(self, on_data, on_connected, on_disconnected, on_error):
        self._on_data = on_data
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_error = on_error
        self._gatt = None
        self._device_name = ""
        self._txd_char = None

    def start_scan(self, on_device_found):
        """Start BLE scan; call on_device_found(name, address) for each result."""
        try:
            from jnius import autoclass, cast, PythonJavaClass, java_method  # noqa: F401

            BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")
            adapter = BluetoothAdapter.getDefaultAdapter()
            if adapter is None:
                self._on_error("蓝牙不可用")
                return

            scanner = adapter.getBluetoothLeScanner()

            class ScanCallback(PythonJavaClass):
                __javainterfaces__ = ["android/bluetooth/le/ScanCallback"]
                __javacontext__ = "app"

                def __init__(self, callback):
                    super().__init__()
                    self._cb = callback

                @java_method("(ILandroid/bluetooth/le/ScanResult;)V")
                def onScanResult(self, callback_type, result):
                    dev = result.getDevice()
                    name = dev.getName() or ""
                    addr = dev.getAddress()
                    self._cb(name, addr, dev)

                @java_method("(I)V")
                def onScanFailed(self, error_code):
                    pass

            self._scan_callback = ScanCallback(on_device_found)
            scanner.startScan(self._scan_callback)
        except Exception as exc:
            self._on_error(f"扫描失败: {exc}")

    def connect(self, java_device):
        """Connect to a Java BluetoothDevice object."""
        try:
            from jnius import autoclass, PythonJavaClass, java_method

            Context = autoclass("android.content.Context")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            ctx = PythonActivity.mActivity

            class GattCallback(PythonJavaClass):
                __javainterfaces__ = ["android/bluetooth/BluetoothGattCallback"]
                __javacontext__ = "app"

                def __init__(self, outer):
                    super().__init__()
                    self._outer = outer

                @java_method("(Landroid/bluetooth/BluetoothGatt;II)V")
                def onConnectionStateChange(self, gatt, status, new_state):
                    STATE_CONNECTED    = 2
                    STATE_DISCONNECTED = 0
                    if new_state == STATE_CONNECTED:
                        gatt.discoverServices()
                    elif new_state == STATE_DISCONNECTED:
                        self._outer._on_disconnected()

                @java_method("(Landroid/bluetooth/BluetoothGatt;I)V")
                def onServicesDiscovered(self, gatt, status):
                    GATT_SUCCESS = 0
                    if status == GATT_SUCCESS:
                        UUID = autoclass("java.util.UUID")
                        svc = gatt.getService(UUID.fromString(SERVICE_UUID))
                        if svc is None:
                            self._outer._on_error("找不到服务 UUID F1F0")
                            return
                        txd = svc.getCharacteristic(UUID.fromString(TXD_UUID))
                        rxd = svc.getCharacteristic(UUID.fromString(RXD_UUID))
                        self._outer._txd_char = txd
                        # Enable notifications for RXD
                        gatt.setCharacteristicNotification(rxd, True)
                        CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
                        desc = rxd.getDescriptor(CCCD_UUID)
                        BluetoothGattDescriptor = autoclass(
                            "android.bluetooth.BluetoothGattDescriptor"
                        )
                        desc.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                        gatt.writeDescriptor(desc)
                        self._outer._on_connected()
                    else:
                        self._outer._on_error(f"服务发现失败: {status}")

                @java_method(
                    "(Landroid/bluetooth/BluetoothGatt;"
                    "Landroid/bluetooth/BluetoothGattCharacteristic;I)V"
                )
                def onCharacteristicChanged(self, gatt, characteristic, _value):
                    data = bytes(characteristic.getValue())
                    self._outer._on_data(data)

                @java_method(
                    "(Landroid/bluetooth/BluetoothGatt;"
                    "Landroid/bluetooth/BluetoothGattCharacteristic;I)V"
                )
                def onCharacteristicWrite(self, gatt, characteristic, status):
                    pass  # fire-and-forget writes

            self._gatt_callback = GattCallback(self)
            self._device_name = java_device.getName() or ""
            self._gatt = java_device.connectGatt(ctx, False, self._gatt_callback)
        except Exception as exc:
            self._on_error(f"连接失败: {exc}")

    def write(self, data: bytes) -> None:
        if self._gatt is None or self._txd_char is None:
            return
        self._txd_char.setValue(data)
        self._gatt.writeCharacteristic(self._txd_char)

    def disconnect(self) -> None:
        if self._gatt:
            try:
                self._gatt.disconnect()
                self._gatt.close()
            except Exception:
                pass
            self._gatt = None

    @property
    def device_name(self) -> str:
        return self._device_name


# ────────────────────────────────────────────────────────────────────────────
# Protocol state machine (Android-specific, synchronous callbacks)
# ────────────────────────────────────────────────────────────────────────────

class WaterProtocol:
    """Maps BLE callbacks to the waterctl protocol state machine."""

    def __init__(self, ble: AndroidBLE, on_stage, on_error):
        self._ble = ble
        self._on_stage = on_stage
        self._on_error = on_error
        self._is_started = False
        self._pending_epilogue = None

    def on_connected(self):
        self._on_stage("pending")
        self._ble.write(START_PROLOGUE)

    def on_disconnected(self):
        self._cancel_epilogue()
        self._is_started = False
        self._on_stage("standby")

    def on_error(self, msg: str):
        self._on_error(msg)

    def on_data(self, raw: bytes):
        try:
            p = self._normalize(raw)
            if p is None:
                return
            d = p[3]

            if d in (0xB0, 0xB1):
                self._cancel_epilogue()
                self._pending_epilogue = threading.Timer(
                    0.5, lambda: self._ble.write(make_start_epilogue(self._ble.device_name))
                )
                self._pending_epilogue.start()

            elif d == 0xAE:
                self._cancel_epilogue()
                # Key auth — deputy.wasm not available on Android; fall back gracefully
                try:
                    from core.solvers import make_unlock_response
                    resp = make_unlock_response(p, self._ble.device_name)
                    self._ble.write(resp)
                except Exception as e:
                    self._on_error(f"密钥派生失败（需要 deputy.wasm）: {e}")

            elif d == 0xAF:
                sub = p[5]
                if sub == 0x55:
                    self._ble.write(make_start_epilogue(self._ble.device_name, True))
                elif sub in (0x01, 0x02, 0x04):
                    raise RuntimeError("WATERCTL INTERNAL Bad key")
                else:
                    self._ble.write(make_start_epilogue(self._ble.device_name, True))

            elif d == 0xB2:
                self._cancel_epilogue()
                self._is_started = True
                self._on_stage("active")

            elif d == 0xB3:
                self._ble.write(END_EPILOGUE)
                self._ble.disconnect()

            elif d in (0xAA, 0xB5, 0xB8):
                pass

            elif d == 0xBA:
                self._ble.write(BA_ACK)

            elif d == 0xBC:
                self._ble.write(OFFLINEBOMB_FIX)

            elif d == 0xC8:
                raise RuntimeError("WATERCTL INTERNAL Refused")

        except Exception as exc:
            self._on_error(str(exc))

    def end_session(self):
        if self._is_started:
            self._ble.write(END_PROLOGUE)

    def _cancel_epilogue(self):
        if self._pending_epilogue:
            self._pending_epilogue.cancel()
            self._pending_epilogue = None

    @staticmethod
    def _normalize(raw: bytes):
        p = bytearray(raw)
        if len(p) >= 3 and p[0] == 0x41 and p[1] == 0x54 and p[2] == 0x2B:
            return None
        if p[0] not in (0xFD, 0x09):
            return None
        if len(p) >= 2 and p[1] == 0x09:
            p = bytearray([0xFD]) + p
        if p[0] == 0x09:
            p = bytearray([0xFD, 0xFD]) + p
        return bytes(p) if len(p) >= 4 else None


# ────────────────────────────────────────────────────────────────────────────
# Kivy UI
# ────────────────────────────────────────────────────────────────────────────

class RoundedButton(Button):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal  = ""
        self.background_color   = (0, 0, 0, 0)
        self.color              = WHITE
        self.font_size          = "18sp"
        self.bold               = True
        self._bg_color          = PINK_DEEP
        with self.canvas.before:
            self._color_instr = Color(*PINK_DEEP)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[24])
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, *_):
        self._rect.pos  = self.pos
        self._rect.size = self.size

    def set_color(self, rgba):
        self._color_instr.rgba = rgba


class WaterApp(App):

    def build(self):
        Window.clearcolor = PINK_PALE

        self._ble = None
        self._protocol = None
        self._java_devices = {}  # name+addr -> java device

        root = BoxLayout(orientation="vertical", padding=24, spacing=16)

        # Title
        title = Label(
            text="🌸 校园饮水机控制器 🌸",
            font_size="22sp",
            bold=True,
            color=PINK_DEEP,
            size_hint_y=None,
            height=60,
        )
        root.add_widget(title)

        subtitle = Label(
            text="kawaii water control ♡",
            font_size="13sp",
            color=PINK_MAIN,
            size_hint_y=None,
            height=28,
        )
        root.add_widget(subtitle)

        root.add_widget(Widget(size_hint_y=None, height=12))

        # Device name label
        self._device_label = Label(
            text="未连接",
            font_size="14sp",
            color=TEXT_DARK,
            size_hint_y=None,
            height=32,
        )
        root.add_widget(self._device_label)

        # Scan button
        scan_btn = RoundedButton(text="🔍 搜索设备", size_hint_y=None, height=52)
        scan_btn.bind(on_press=self._on_scan)
        root.add_widget(scan_btn)

        # Main action button
        self._main_btn = RoundedButton(text="▶ 开启用水", size_hint_y=None, height=60)
        self._main_btn.bind(on_press=self._on_main)
        self._main_btn.disabled = True
        root.add_widget(self._main_btn)

        # Status
        self._status_label = Label(
            text="等待连接…",
            font_size="13sp",
            color=PINK_MAIN,
            size_hint_y=None,
            height=32,
        )
        root.add_widget(self._status_label)

        root.add_widget(Widget())  # spacer

        return root

    # ── Scan ──

    def _on_scan(self, *_):
        self._device_label.text = "扫描中…"
        self._java_devices = {}
        self._found_items  = []

        self._ble = AndroidBLE(
            on_data=self._on_data,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            on_error=self._show_error,
        )
        self._ble.start_scan(self._on_device_found)

        # Stop scan after 8 seconds and show picker
        Clock.schedule_once(self._show_device_picker, 8)

    def _on_device_found(self, name, addr, java_dev):
        key = f"{name}|{addr}"
        if key not in self._java_devices:
            self._java_devices[key] = java_dev
            self._found_items.append((name or addr, key))

    @mainthread
    def _show_device_picker(self, *_):
        if not self._found_items:
            self._show_error("未发现蓝牙设备，请确认已开启蓝牙并靠近设备。")
            return

        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        scroll  = ScrollView(size_hint_y=None, height=300)
        inner   = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None)
        inner.bind(minimum_height=inner.setter("height"))

        popup_ref = []

        for display_name, key in self._found_items:
            btn = Button(
                text=display_name,
                size_hint_y=None,
                height=46,
                background_color=(*PINK_MAIN[:3], 1),
                color=WHITE,
            )

            def make_handler(k):
                def handler(*_):
                    popup_ref[0].dismiss()
                    self._connect_device(k)
                return handler

            btn.bind(on_press=make_handler(key))
            inner.add_widget(btn)

        scroll.add_widget(inner)
        content.add_widget(Label(text="选择设备", font_size="15sp", color=PINK_DEEP,
                                 size_hint_y=None, height=36))
        content.add_widget(scroll)

        popup = Popup(
            title="🌸 搜索到的设备",
            content=content,
            size_hint=(0.88, None),
            height=420,
        )
        popup_ref.append(popup)
        popup.open()

    def _connect_device(self, key):
        java_dev = self._java_devices.get(key)
        if java_dev is None:
            return
        self._protocol = WaterProtocol(
            self._ble,
            on_stage=self._update_stage,
            on_error=self._show_error,
        )
        self._ble._on_data         = self._protocol.on_data
        self._ble._on_connected    = self._protocol.on_connected
        self._ble._on_disconnected = self._protocol.on_disconnected
        self._ble.connect(java_dev)

    # ── Stage updates ──

    @mainthread
    def _update_stage(self, stage: str):
        if stage == "pending":
            self._main_btn.text     = "请稍候…"
            self._main_btn.disabled = True
            self._main_btn.set_color(PINK_MAIN)
            self._status_label.text = "正在握手…"
        elif stage == "active":
            self._main_btn.text     = "⏹ 结束用水"
            self._main_btn.disabled = False
            self._main_btn.set_color(PINK_DEEP)
            self._status_label.text = "用水中 ♡"
        else:
            self._main_btn.text     = "▶ 开启用水"
            self._main_btn.disabled = True
            self._main_btn.set_color(PINK_MAIN)
            self._device_label.text = "未连接"
            self._status_label.text = "等待连接…"

    def _on_main(self, *_):
        if self._protocol is None:
            return
        if self._protocol._is_started:
            self._protocol.end_session()
        else:
            pass  # already handled by connect flow

    # ── BLE forwarding helpers ──

    def _on_data(self, data):
        if self._protocol:
            self._protocol.on_data(data)

    def _on_connected(self):
        if self._protocol:
            self._protocol.on_connected()

    def _on_disconnected(self):
        if self._protocol:
            self._protocol.on_disconnected()

    @mainthread
    def _show_error(self, msg: str):
        popup = Popup(
            title="🚫 出错了",
            content=Label(text=msg, color=TEXT_DARK, text_size=(300, None)),
            size_hint=(0.85, None),
            height=220,
        )
        popup.open()


if __name__ == "__main__":
    WaterApp().run()
