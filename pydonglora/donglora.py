import serial, time, random
from typing import Callable, overload, Literal, Any
from pydonglora.data import *
from pydonglora.helper import *

Callback = Callable[..., None | type[Keep]]

class DongloraBase:
    def __init__(self, port: str) -> None:
        self.serial = serial.Serial(port, 115200, timeout=0)
        self._tag = 1
        self._rxbuf = bytearray()
        self.callbacks: dict[int, Callable] = {}
        self.callback_args: dict[int, tuple[tuple, dict]] = {}
        self.rx_callback: Callable[[RXPacket]] | None = None
        self.last_packet_time = 0
        self._payload_len_limit: None | int = None
    @overload
    def _send(self, type: Literal[Command.TX],
        payload: bytes, callback: Callable[..., None | type[Keep]] | None = None,
        *cargs: Any, **ckwargs: Any
    ) -> int: ...

    @overload
    def _send(self, type: Command,
        payload: bytes, callback: Callable[..., None | type[Keep]] | None = None,
        *cargs: Any, **ckwargs: Any
    ) -> int: ...

    def _send(self, type: Command,
        payload: bytes,
        callback: Callback | None = None,
        *cargs: Any, **ckwargs: Any
    ) -> int:
        if self._payload_len_limit is not None and len(payload) > self._payload_len_limit: raise ValueError("payload too long")

        data = struct.pack("<BH", type, self._tag) + payload
        self.serial.write(cobs_encode(data + struct.pack("<H", crc16(data))) + b"\0")

        if callable(callback):
            self.callbacks[self._tag] = callback
            self.callback_args[self._tag] = (cargs, ckwargs)

        sent_tag = self._tag
        self._tag += 1
        if self._tag > 0xffff: self._tag = 1
        self.last_packet_time = time.monotonic()
        return sent_tag
    def loop(self):
        self._rxbuf.extend(self.serial.read_all())
        while b"\x00" in self._rxbuf:
            frame, _, self._rxbuf = self._rxbuf.partition(b"\x00")
            if not frame: continue
            frame_data = cobs_decode(bytes(frame))
            if len(frame_data) < 5: continue

            try: packet = DongloraPacket.from_bytes(frame_data)
            except Discard: continue

            if packet.type == Command.ERR: raise DongloraError(packet.tag, *struct.unpack("<H", packet.payload))
            if packet.type == Command.RX and self.rx_callback: self.rx_callback(RXPacket.from_bytes(packet.payload))

            if packet.tag == 0: continue
            if (callback := self.callbacks.get(packet.tag)) and callable(callback): 
                cargs, ckwargs = self.callback_args.get(packet.tag, (tuple(),{}))

                if packet.type == Command.TX_DONE: x = callback(TXPacket.from_bytes(packet.payload), *cargs, **ckwargs)
                else: x = callback(packet, *cargs, **ckwargs)

                if x != Keep:
                    self.callbacks.pop(packet.tag, None)
                    self.callback_args.pop(packet.tag, None)

        # Don't let the inactivity timer expire of 1000 ms
        # protocol says host SHOULD send it every 500 ms
        def _ping(packet: DongloraPacket): assert packet.type == Command.OK
        if (time.monotonic()-self.last_packet_time) > .500: self._send(Command.PING, b"", _ping)
class Donglora(DongloraBase):
    def __init__(self, port: str) -> None:
        super().__init__(port)
        self._lock = True
        self._tx_power_dbm = 22
        self._frequency: int | None = None
        self._sf: int | None = None
        self._bw: LoRaBandwidth | None = None
        self._cr: int | None = None
        self._preamble_len: int | None = None
        self._sync_word: int | None = None
        self._header_mode: bool | None = None
        self._crc_on: bool | None = None
        self._iq_invert: bool | None = None
        self._info: DongloraDeviceInfo | None = None
        self._configured: bool = False
        self._transmitting: bool = False
        self._get_info()
    def meshtastic(self) -> Donglora:
        # LongFast preset
        self._frequency = 869525000
        self._sf = 5
        self._bw = LoRaBandwidth.KHz_250
        self._cr = LoRaCodingRate.CR_4_8
        self._preamble_len = 16
        self._sync_word = 0x2B
        self._header_mode = False
        self._crc_on = True
        self._iq_invert = False
        self._reconfigure(True)
        self._lock = False
        return self # its so you can do a Donglora(...).meshtastic() one liner
    def meshcore(self) -> Donglora:
        self._frequency = 869618000
        self._sf = 8
        self._bw = LoRaBandwidth.KHz_62
        self._cr = LoRaCodingRate.CR_4_8
        self._preamble_len = 16
        self._sync_word = 0x1424
        self._header_mode = False
        self._crc_on = True
        self._iq_invert = False
        self._reconfigure(True)
        self._lock = False
        return self
    def _get_info(self):
        def callback(packet: DongloraPacket):
            assert packet.type == Command.OK
            self._info = DongloraDeviceInfo.from_bytes(packet.payload)
            if self._info.proto_major != 1:
                # Docs say host MUST NOT attempt to use device
                raise ProtocolIncompatible("Protocol major isn't 1")
            self._payload_len_limit = self._info.max_payload_bytes + 20
        self._send(Command.GET_INFO, b"", callback)
        while not self._info: self.loop() # TODO: maybe add a timeout
        return self._info
    @property
    def device_info(self):
        if self._info: return self._info
        return self._get_info()
    def __enter__(self):
        self.settings_open()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.settings_commit()
        return False  # Don't suppress exceptions
    def settings_open(self): self._lock = True
    def settings_commit(self):
        self._lock = False
        self._reconfigure()
    def _reconfigure(self, force: bool = False):
        if self._lock and not force: return

        if self._frequency is None or self._sf is None \
        or self._bw is None or self._cr is None \
        or self._preamble_len is None or self._sync_word is None \
        or self._header_mode is None or self._crc_on is None \
        or self._iq_invert is None: raise ValueError("Set all settings first.")

        if self._tx_power_dbm > self.device_info.tx_power_max_dbm \
                or self._tx_power_dbm < self.device_info.tx_power_min_dbm:
            raise ValueError("TX power is not within range")
        if self._frequency > self.device_info.freq_max_hz \
                or self._frequency < self.device_info.freq_min_hz:
            raise ValueError("Frequency is not within range")

        params = ConfigLoRa(self._frequency, self._sf, self._bw, 
                            self._cr, self._preamble_len, self._sync_word, 
                            self._tx_power_dbm, self._header_mode, 
                            self._crc_on, self._iq_invert)

        self._configured = False
        def callback(packet: DongloraPacket):
            assert packet.type == Command.OK
            data = ConfigResponse.from_bytes(packet.payload)
            assert data.result == ConfigResult.APPLIED
            assert data.owner == ConfigOwner.MINE
            self._configured = True
        self._send(Command.SET_CONFIG, b"\x01" + bytes(params), callback)
        while not self._configured: self.loop() # Block until we are sure we are configured
    @property
    def frequency(self): return self._frequency
    @frequency.setter
    def frequency(self, value):
        if value != self._frequency:
            self._frequency = value
            self._reconfigure()
    @property
    def sf(self): return self._sf
    @sf.setter
    def sf(self, value):
        if value != self._sf:
            self._sf = value
            self._reconfigure()

    @property
    def bw(self): return self._bw
    @bw.setter
    def bw(self, value):
        if value != self._bw:
            self._bw = value
            self._reconfigure()

    @property
    def cr(self): return self._cr
    @cr.setter
    def cr(self, value):
        if value != self._cr:
            self._cr = value
            self._reconfigure()

    @property
    def preamble_len(self): return self._preamble_len
    @preamble_len.setter
    def preamble_len(self, value):
        if value != self._preamble_len:
            self._preamble_len = value
            self._reconfigure()

    @property
    def sync_word(self): return self._sync_word
    @sync_word.setter
    def sync_word(self, value):
        if value != self._sync_word:
            self._sync_word = value
            self._reconfigure()

    @property
    def tx_power(self): return self._tx_power_dbm
    @tx_power.setter
    def tx_power(self, value):
        if value != self._tx_power_dbm:
            self._tx_power_dbm = value
            self._reconfigure()

    def start_rx(self):
        assert self._configured
        self._send(Command.RX_START, b"")
        return self
    def stop_rx(self): 
        assert self._configured
        self._send(Command.RX_STOP, b"")
        return self

    def transmit(self, data: bytes, skip_cad: bool = False, blocking: bool = False):
        while self._transmitting and blocking: self.loop()
        if self._transmitting: raise AlreadyTransmitting # Allow one transmission sent to device - some can handle more but my test one doesn't (RP2040)

        assert self._configured
        if len(data) > self.device_info.max_payload_bytes: raise ValueError("payload too long")

        data = struct.pack("<?", skip_cad) + data

        def callback(packet: DongloraPacket | TXPacket):
            if isinstance(packet, DongloraPacket): return Keep

            if packet.result == 0:
                self._transmitting = False
                return
            elif packet.result == 1:  # Channel busy
                time.sleep(random.random() * 5)
                self._send(Command.TX, data, callback)
            elif packet.result == 2:  # Cancelled
                self._transmitting = False
                return
        self._transmitting = True
        self._send(Command.TX, data, callback)
        while self._transmitting: self.loop()