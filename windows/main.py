"""
Windows native EXE — PyQt6 UI + bleak (WinRT) for water dispenser control.

Build with PyInstaller:
    pyinstaller windows/main.spec

Or directly:
    pyinstaller --onefile --windowed --name SchoolWater windows/main.py
"""

import asyncio
import sys
import threading
from datetime import datetime

import pytz
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# ── Shared protocol helpers (same as core/) ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.bluetooth import Stage, WaterController
from core.payloads import SERVICE_UUID, TXD_UUID, RXD_UUID

# ────────────────────────────────────────────────────────────────────────────
# Palette
# ────────────────────────────────────────────────────────────────────────────

PINK_DEEP  = "#E75480"
PINK_MAIN  = "#F48FB1"
PINK_LIGHT = "#FCE4EC"
PINK_PALE  = "#FFF0F5"
TEXT_DARK  = "#5A3A4A"
WHITE      = "#FFFFFF"

STYLE_SHEET = f"""
QMainWindow, QDialog {{
    background-color: {PINK_PALE};
}}
QLabel#title {{
    font-size: 22px;
    font-weight: bold;
    color: {PINK_DEEP};
}}
QLabel#subtitle {{
    font-size: 12px;
    color: {PINK_MAIN};
}}
QLabel#device-name {{
    font-size: 13px;
    color: {TEXT_DARK};
    background-color: {PINK_LIGHT};
    border-radius: 12px;
    padding: 4px 12px;
}}
QLabel#status {{
    font-size: 12px;
    color: {PINK_MAIN};
}}
QPushButton#scan-btn {{
    background-color: {PINK_MAIN};
    color: {WHITE};
    border: none;
    border-radius: 18px;
    padding: 8px 24px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#scan-btn:hover {{
    background-color: {PINK_DEEP};
}}
QPushButton#main-btn {{
    background-color: {PINK_DEEP};
    color: {WHITE};
    border: none;
    border-radius: 22px;
    padding: 12px 40px;
    font-size: 17px;
    font-weight: bold;
}}
QPushButton#main-btn:hover {{
    background-color: #D04070;
}}
QPushButton#main-btn:disabled {{
    background-color: {PINK_MAIN};
    color: rgba(255,255,255,0.7);
}}
QPushButton#main-btn.active {{
    background-color: #FF5C8A;
}}
QListWidget {{
    background-color: {WHITE};
    border: 1px solid {PINK_MAIN};
    border-radius: 10px;
    font-size: 13px;
    color: {TEXT_DARK};
}}
QListWidget::item:selected {{
    background-color: {PINK_MAIN};
    color: {WHITE};
}}
"""

# ────────────────────────────────────────────────────────────────────────────
# Background worker threads
# ────────────────────────────────────────────────────────────────────────────

class ScanThread(QThread):
    """Runs BLE scan in a background asyncio loop."""
    devices_found = pyqtSignal(list)  # list of (name, address, BLEDevice)
    error         = pyqtSignal(str)

    def run(self):
        async def _scan():
            devs = await BleakScanner.discover(timeout=8.0)
            results = [(d.name or d.address, d.address, d) for d in devs]
            self.devices_found.emit(results)

        try:
            asyncio.run(_scan())
        except Exception as exc:
            self.error.emit(str(exc))


class BLEWorker(QThread):
    """Runs the WaterController in a background asyncio loop, bridging signals to Qt."""
    stage_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str, bool)  # message, is_fatal
    device_name_updated = pyqtSignal(str)

    def __init__(self, device: BLEDevice):
        super().__init__()
        self._device = device
        self._ctrl: WaterController | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        self._ctrl = WaterController()
        self._ctrl.on_stage_change = lambda s: self.stage_changed.emit(s.value)
        self._ctrl.on_error = lambda m, f: self.error_occurred.emit(m, f)

        self.device_name_updated.emit(self._device.name or self._device.address)
        await self._ctrl.connect(self._device)

        # Keep the event loop alive until we're done
        while self._ctrl._stage != Stage.STANDBY:
            await asyncio.sleep(0.2)

    def request_end(self):
        if self._ctrl and self._loop:
            asyncio.run_coroutine_threadsafe(self._ctrl.end(), self._loop)

    def request_disconnect(self):
        if self._ctrl and self._loop:
            asyncio.run_coroutine_threadsafe(self._ctrl.disconnect(), self._loop)


# ────────────────────────────────────────────────────────────────────────────
# Device picker dialog
# ────────────────────────────────────────────────────────────────────────────

class DevicePickerDialog(QDialog):
    def __init__(self, devices: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌸 选择蓝牙设备")
        self.setMinimumWidth(360)
        self.selected_device = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        lbl = QLabel("请选择水控器设备：")
        lbl.setStyleSheet(f"color: {PINK_DEEP}; font-weight: bold; font-size: 14px;")
        layout.addWidget(lbl)

        self._list = QListWidget()
        for name, addr, dev in devices:
            item = QListWidgetItem(f"{name}  [{addr}]")
            item.setData(Qt.ItemDataRole.UserRole, dev)
            self._list.addItem(item)
        layout.addWidget(self._list)

        btn = QPushButton("连接 ♡")
        btn.setObjectName("scan-btn")
        btn.clicked.connect(self._accept)
        layout.addWidget(btn)

    def _accept(self):
        items = self._list.selectedItems()
        if items:
            self.selected_device = items[0].data(Qt.ItemDataRole.UserRole)
            self.accept()


# ────────────────────────────────────────────────────────────────────────────
# Main window
# ────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("💧 校园饮水机控制器")
        self.setFixedSize(420, 480)
        self._ble_worker: BLEWorker | None = None
        self._scan_thread: ScanThread | None = None
        self._stage = "standby"
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)
        layout.setContentsMargins(40, 30, 40, 30)

        # Title
        title = QLabel("🌸💧 校园饮水机控制器 💧🌸")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("kawaii water control ♡")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        layout.addSpacing(8)

        # Device name
        self._device_lbl = QLabel("未连接")
        self._device_lbl.setObjectName("device-name")
        self._device_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._device_lbl)

        layout.addSpacing(8)

        # Scan button
        self._scan_btn = QPushButton("🔍 搜索设备")
        self._scan_btn.setObjectName("scan-btn")
        self._scan_btn.clicked.connect(self._on_scan)
        layout.addWidget(self._scan_btn)

        # Main button
        self._main_btn = QPushButton("▶ 开启用水")
        self._main_btn.setObjectName("main-btn")
        self._main_btn.setEnabled(False)
        self._main_btn.clicked.connect(self._on_main_click)
        layout.addWidget(self._main_btn)

        # Status
        self._status_lbl = QLabel("等待连接…")
        self._status_lbl.setObjectName("status")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_lbl)

        layout.addStretch()

        # About
        about_lbl = QLabel('<a href="#" style="color:#F48FB1;">✨ 关于 / About</a>')
        about_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_lbl.linkActivated.connect(self._show_about)
        layout.addWidget(about_lbl)

    # ── Scan ──

    def _on_scan(self):
        self._scan_btn.setEnabled(False)
        self._status_lbl.setText("扫描中…")
        self._scan_thread = ScanThread()
        self._scan_thread.devices_found.connect(self._on_devices_found)
        self._scan_thread.error.connect(lambda e: self._show_error(e, False))
        self._scan_thread.finished.connect(lambda: self._scan_btn.setEnabled(True))
        self._scan_thread.start()

    def _on_devices_found(self, devices: list):
        if not devices:
            self._show_error("未发现蓝牙设备。请确认蓝牙已开启并靠近设备。", False)
            return

        dlg = DevicePickerDialog(devices, self)
        dlg.setStyleSheet(STYLE_SHEET)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_device:
            self._start_connection(dlg.selected_device)

    # ── Connect ──

    def _start_connection(self, device: BLEDevice):
        self._ble_worker = BLEWorker(device)
        self._ble_worker.stage_changed.connect(self._on_stage_change)
        self._ble_worker.error_occurred.connect(self._show_error)
        self._ble_worker.device_name_updated.connect(
            lambda n: self._device_lbl.setText(f"已连接：{n}")
        )
        self._ble_worker.start()

    # ── Stage ──

    def _on_stage_change(self, stage: str):
        self._stage = stage
        if stage == "pending":
            self._main_btn.setText("请稍候…")
            self._main_btn.setEnabled(False)
            self._status_lbl.setText("正在握手…")
        elif stage == "active":
            self._main_btn.setText("⏹ 结束用水")
            self._main_btn.setEnabled(True)
            self._status_lbl.setText("用水中 ♡")
        else:
            self._main_btn.setText("▶ 开启用水")
            self._main_btn.setEnabled(False)
            self._device_lbl.setText("未连接")
            self._status_lbl.setText("等待连接…")

    def _on_main_click(self):
        if self._stage == "active" and self._ble_worker:
            self._ble_worker.request_end()

    # ── Error / About ──

    def _show_error(self, msg: str, is_fatal: bool):
        friendly = msg
        if "Unknown RXD data" in msg:
            friendly = "接收到未知数据，可能不影响使用。"
        elif "Refused" in msg or "Bad key" in msg:
            friendly = "水控器拒绝启动。请勿多次重试，以免设备锁定。"
        elif "Operation timed out" in msg:
            friendly = "操作超时，请重试。"
        elif "No Services" in msg:
            friendly = "不支持的设备型号。"

        box = QMessageBox(self)
        box.setWindowTitle("🚫 出错了")
        box.setText(friendly)
        box.setIcon(QMessageBox.Icon.Warning)
        box.exec()

        if is_fatal and self._ble_worker:
            self._ble_worker.request_disconnect()

    def _show_about(self, *_):
        box = QMessageBox(self)
        box.setWindowTitle("🌸 关于")
        box.setText(
            "校园饮水机蓝牙控制器\n\n"
            "基于 celesWuff/waterctl 协议\n"
            "♡ 少女风格主题 ♡\n\n"
            "Windows 原生客户端（PyQt6 + bleak）"
        )
        box.exec()

    def closeEvent(self, event):
        if self._ble_worker:
            self._ble_worker.request_disconnect()
        event.accept()


# ────────────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)

    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
