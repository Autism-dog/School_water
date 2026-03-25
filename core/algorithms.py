"""
CRC algorithms ported from celesWuff/waterctl/src/algorithms.ts
"""


def crc16_changgong(s: str) -> int:
    """CRC-16/ChangGong
    width=16, poly=0x8005, init=0xe808, refin=true, refout=true, xorout=0x0000
    Used to compute device name checksum for the B2 (start epilogue) payload.
    """
    crc = 0x1017
    for c in s:
        crc ^= ord(c)
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def crc16_cgaeaf(data: bytes) -> int:
    """CRC-16/CGAEAF (ChangGong AE/AF)
    width=16, poly=0x8005, init=0xf856, refin=true, refout=true, xorout=0x0075
    Truncated to lower 8 bits.
    Used to compute the checksum in the AE/AF (unlock) exchange.
    """
    crc = 0x6A1F
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return (crc ^ 0x75) & 0xFF
