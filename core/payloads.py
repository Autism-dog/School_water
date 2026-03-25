"""
Static protocol payloads ported from celesWuff/waterctl/src/payloads.ts

BLE service/characteristic UUIDs:
  Service  : 0xF1F0
  TXD (write)   : 0xF1F1
  RXD (notify)  : 0xF1F2

Session flow:
  Connect → send START_PROLOGUE
  → receive B0/B1 (or AE for new firmware)
  → send makeStartEpilogue()
  → receive B2 (session active)
  ... use water ...
  → send END_PROLOGUE
  → receive B3
  → send END_EPILOGUE → disconnect
"""

# Full 128-bit UUIDs for use with bleak
SERVICE_UUID = "0000f1f0-0000-1000-8000-00805f9b34fb"
TXD_UUID = "0000f1f1-0000-1000-8000-00805f9b34fb"  # write
RXD_UUID = "0000f1f2-0000-1000-8000-00805f9b34fb"  # notify

# Send first; wait for B0, B1 (old fw) or AE (new fw)
START_PROLOGUE = bytes([0xFE, 0xFE, 0x09, 0xB0, 0x01, 0x01, 0x00, 0x00])

# Send when ending the session; wait for B3
END_PROLOGUE = bytes([0xFE, 0xFE, 0x09, 0xB3, 0x00, 0x00])

# Send after B3 is received; then disconnect
END_EPILOGUE = bytes([0xFE, 0xFE, 0x09, 0xB4, 0x00, 0x00])

# Send if BC is received (offline-bomb clear)
OFFLINEBOMB_FIX = bytes([0xFE, 0xFE, 0x09, 0xBC, 0x00, 0x00])

# Send if BA is received (user-info upload ACK — we fake it)
BA_ACK = bytes([0xFE, 0xFE, 0x09, 0xBA, 0x00, 0x00])
