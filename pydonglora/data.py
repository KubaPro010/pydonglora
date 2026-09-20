from enum import IntEnum, StrEnum
from dataclasses import dataclass
import struct
from pydonglora.helper import crc16

class Keep: ...
class Discard(Exception): ...
class ProtocolIncompatible(BaseException): ...

class Command(IntEnum):
    RESERVED = 0
    PING = 1
    GET_INFO = 2
    SET_CONFIG = 3
    TX = 4
    RX_START = 5
    RX_STOP = 6
    OK = 0x80
    ERR = 0x81
    RX = 0xC0
    TX_DONE = 0xC1
class LoRaBandwidth(IntEnum):
    KHz_1600 = 13
    KHz_800 = 12
    KHz_500 = 9
    KHz_400 = 11
    KHz_250 = 8
    KHz_200 = 10
    KHz_125 = 7
    KHz_62 = 6
    KHz_41 = 5
    KHz_31 = 4
    KHz_20 = 3
    KHz_15 = 2
    KHz_10 = 1
    KHz_7 = 0
class LoRaCodingRate(IntEnum):
    CR_4_5 = 0
    CR_4_6 = 1
    CR_4_7 = 2
    CR_4_8 = 3

@dataclass
class ConfigLoRa:
    freq_hz: int
    sf: int
    bw: int
    cr: int
    preamble_len: int
    sync_word: int
    tx_power_dbm: int
    implicit_header: bool
    payload_crc: bool
    iq_invert: bool
    def __bytes__(self):
        return struct.pack("<L3B2Hb3?", self.freq_hz, self.sf, self.bw, self.cr, self.preamble_len, self.sync_word, self.tx_power_dbm, self.implicit_header, self.payload_crc, self.iq_invert)
    def __len__(self): return 15

class ConfigResult(IntEnum):
    APPLIED = 0
    ALREADY_MATCHED = 1
    LOCKED_MISMATCH = 3
class ConfigOwner(IntEnum):
    NONE = 0
    MINE = 1
    OTHER = 2
@dataclass
class ConfigResponse:
    result: ConfigResult
    owner: ConfigOwner
    current_modulation: int
    current_params: bytes
    @staticmethod
    def from_bytes(value: bytes):
        self = __class__(ConfigResult.LOCKED_MISMATCH, ConfigOwner.NONE, 0, b"")
        self.result, self.owner, self.current_modulation = struct.unpack_from("<3B", value)
        self.current_params = value[3:]
        return self

@dataclass
class RXPacket:
    rssi: float | int
    snr: float | int
    freq_err: int
    timestamp_μs: int
    crc_valid: bool
    packets_dropped: int
    loopback: bool
    payload: bytes
    @staticmethod
    def from_bytes(value: bytes):
        self = __class__(0,0,0,0,False,0,False,b"")
        self.rssi, self.snr, self.freq_err, self.timestamp_μs, \
            self.crc_valid, self.packets_dropped, self.loopback = struct.unpack_from("<2hlQ?H?", value)
        self.rssi /= 10
        self.snr /= 10
        self.payload = value[20:]
        return self

@dataclass
class TXPacket:
    result: int
    airtime_μs: int
    @staticmethod
    def from_bytes(value: bytes):
        self = __class__(2,0)
        self.result, self.airtime_μs = struct.unpack_from("<BL", value)
        return self

@dataclass
class DongloraPacket:
    type: Command
    tag: int
    payload: bytes = b""
    @property
    def crc(self): return crc16(struct.pack("<BH", self.type, self.tag) + self.payload)
    @staticmethod
    def from_bytes(value: bytes):
        if len(value) < 5: raise ValueError("packet too short")
        packet = __class__(Command.RESERVED, 0)

        packet.type, packet.tag = struct.unpack_from("<BH", value)
        try: packet.type = Command(packet.type)
        except ValueError:
            # Documentation explicitly tells that hosts MUST silently discard frames with unknown types
            # with MSB = 1 (from device)
            if (packet.type & (1 << 7)) != 0: raise Discard
            raise
        packet.payload = value[3:-2]

        expected_crc, = struct.unpack_from("<H", value, len(value) - 2)

        if packet.crc != expected_crc: raise Discard
            # raise ValueError(
            #     f"invalid CRC: expected {expected_crc:04x}, "
            #     f"calculated {packet.crc:04x}"
            # )

        return packet

class RadioChipID(IntEnum):
    Unknown = 0
    SX1261 = 1
    SX1262 = 2
    SX1268 = 3
    LLCC68 = 4
    SX1272 = 0x10
    SX1276 = 0x11
    SX1277 = 0x12
    SX1278 = 0x13
    SX1279 = 0x14
    SX1280 = 0x20
    SX1281 = 0x21
    LR1110 = 0x30
    LR1120 = 0x31
    LR1121 = 0x32
    LR2021 = 0x40

class CapabilityBitmap:
    def __init__(self, value: int) -> None: self.value: int = value
    @property
    def LoRa(self): return bool(self.value & 1)
    @property
    def FSK(self): return bool(self.value & (1 << 1))
    @property
    def GFSK(self): return bool(self.value & (1 << 2))
    @property
    def LR_FHSS(self): return bool(self.value & (1 << 3))
    @property
    def FLRC(self): return bool(self.value & (1 << 4))
    @property
    def MSK(self): return bool(self.value & (1 << 5))
    @property
    def GMSK(self): return bool(self.value & (1 << 6))
    @property
    def BLE(self): return bool(self.value & (1 << 7))
    @property
    def CAD(self): return bool(self.value & (1 << 16))
    @property
    def IQ_Invert(self): return bool(self.value & (1 << 17))
    @property
    def Ranging(self): return bool(self.value & (1 << 18))
    @property
    def GNSS(self): return bool(self.value & (1 << 19))
    @property
    def WiFiMAC(self): return bool(self.value & (1 << 20))
    @property
    def SpectralScan(self): return bool(self.value & (1 << 21))
    @property
    def FullDuplex(self): return bool(self.value & (1 << 22))
    @property
    def Multiclient(self): return bool(self.value & (1 << 32))
    def __repr__(self) -> str:
        capabilities = [
            name for name in (
                "LoRa",
                "FSK",
                "GFSK",
                "LR_FHSS",
                "FLRC",
                "MSK",
                "GMSK",
                "BLE",
                "CAD",
                "IQ_Invert",
                "Ranging",
                "GNSS",
                "WiFiMAC",
                "SpectralScan",
                "FullDuplex",
                "Multiclient",
            ) if getattr(self, name)
        ]

        return (
            f"{type(self).__name__}("
            f"value=0x{self.value:X}, "
            f"capabilities=[{', '.join(capabilities)}]"
            f")"
        )

@dataclass
class DongloraDeviceInfo:
    proto_major: int
    proto_minor: int
    fw_major: int
    fw_minor: int
    fw_patch: int
    radio_chip_id: RadioChipID
    capability_bitmap: CapabilityBitmap
    supported_sf_bitmap: int
    supported_bw_bitmap: int
    max_payload_bytes: int
    rx_queue_capacity: int
    tx_queue_capacity: int
    freq_min_hz: int
    freq_max_hz: int
    tx_power_min_dbm: int
    tx_power_max_dbm: int
    mcu_uid: bytes
    radio_uid: bytes
    @property
    def radio_uid_len(self): return len(self.radio_uid)
    @property
    def mcu_uid_len(self): return len(self.mcu_uid)
    @staticmethod
    def from_bytes(value: bytes):
        self = __class__(0,0,0,0,0,RadioChipID.Unknown,CapabilityBitmap(0),0,0,0,0,0,0,0,0,0,b"",b"")
        self.proto_major, self.proto_minor, self.fw_major, self.fw_minor, self.fw_patch, \
        self.radio_chip_id, self.capability_bitmap.value, self.supported_sf_bitmap, self.supported_bw_bitmap, \
        self.max_payload_bytes, self.rx_queue_capacity, self.tx_queue_capacity, self.freq_min_hz, self.freq_max_hz, \
        self.tx_power_min_dbm, self.tx_power_max_dbm = struct.unpack_from("<5BHQ5H2L2b", value)

        self.radio_chip_id = RadioChipID(self.radio_chip_id)

        offset = 35

        mcu_uid_len = value[offset]
        offset += 1
        self.mcu_uid = value[offset:offset + mcu_uid_len]
        offset += mcu_uid_len
        radio_uid_len = value[offset]
        offset += 1
        self.radio_uid = value[offset:offset + radio_uid_len]
        return self

class DongloraError(Exception):
    class ErrorCode(IntEnum):
        EPARAM = 1
        ELENGTH = 2
        ENOTCONFIGURED = 3
        EMODULATION = 4
        EUNKNOWN_CMD = 5
        EBUSY = 6
        ERADIO = 0x101
        EFRAME = 0x102
        EINTERNAL = 0x103
    class ErrorCodeMeaning(StrEnum):
        EPARAM = "A parameter value is out of range or invalid."
        ELENGTH = "Payload length is wrong for the command or modulation."
        ENOTCONFIGURED = "Command requires CONFIGURED; device is UNCONFIGURED."
        EMODULATION = "Requested modulation is not supported by this chip."
        EUNKNOWN_CMD = "Unknown command type byte."
        EBUSY = "Transient: TX queue full. Host should wait and retry."
        ERADIO = "Radio SPI error or unexpected hardware state."
        EFRAME = "Inbound frame had bad CRC, bad COBS, or wrong length."
        EINTERNAL = "Firmware encountered an unexpected internal condition."
    def __init__(self, tag: int, code: int, *args: object) -> None:
        super().__init__(f"{getattr(self.ErrorCodeMeaning, self.ErrorCode(code).name)} - at tag {tag}", *args)