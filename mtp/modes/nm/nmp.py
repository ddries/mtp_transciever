"""NMP-1: formato binario y máquina de estados (secciones 4 a 9 del PDF)."""

import logging
import random
import struct
import time
import zlib
from pathlib import Path

HEADER = struct.Struct("<HI")
FRAME = struct.Struct("<BI27s")
CHUNK_SIZE = 27
MAX_CHUNKS = 32
MAX_FILE = MAX_CHUNKS * CHUNK_SIZE - HEADER.size  # 858 bytes
FULL_MASK = (1 << MAX_CHUNKS) - 1
ZERO_DATA = bytes(CHUNK_SIZE)
STATUS, DATA = 0x20, 0x40
SLOT, CW, T_ASK = 0.002, 16, 0.300

STOPPED, IDLE, BACKOFF, TX = "STOPPED", "IDLE", "BACKOFF", "TX"
GO, STOP, RX, ASK, EXP, DONE = "GO", "STOP", "RX", "ASK", "EXP", "DONE"


def n_from_header(chunk):
    if len(chunk) != CHUNK_SIZE:
        raise ValueError("Un fragmento debe ocupar 27 bytes")
    length, _ = HEADER.unpack_from(chunk)
    if length > MAX_FILE:
        raise ValueError("LEN supera los 858 bytes permitidos")
    return (HEADER.size + length + CHUNK_SIZE - 1) // CHUNK_SIZE


def fragment(data):
    """Archivo binario -> cabecera LEN/CRC-32 y fragmentos con relleno cero."""
    if len(data) > MAX_FILE:
        logging.warning("Archivo truncado: se usarán solo los primeros %d bytes", MAX_FILE)
        data = data[:MAX_FILE]
    stream = HEADER.pack(len(data), zlib.crc32(data)) + data
    return [stream[i:i + CHUNK_SIZE].ljust(CHUNK_SIZE, b"\0")
            for i in range(0, len(stream), CHUNK_SIZE)]


def reconstruct(chunks):
    """Devuelve exactamente LEN bytes, o rechaza un archivo incompleto/corrupto."""
    if not chunks or chunks[0] is None:
        raise ValueError("Falta el fragmento cero")
    n = n_from_header(chunks[0])
    if len(chunks) < n or any(c is None or len(c) != CHUNK_SIZE for c in chunks[:n]):
        raise ValueError("Faltan fragmentos o su tamaño es incorrecto")
    length, expected_crc = HEADER.unpack_from(chunks[0])
    data = b"".join(chunks[:n])[HEADER.size:HEADER.size + length]
    if zlib.crc32(data) != expected_crc:
        raise ValueError("CRC-32 incorrecto")
    return data


def pack_frame(kind, have, seq=0, data=ZERO_DATA):
    """Construye tramas canónicas de exactamente 32 bytes."""
    if kind not in (STATUS, DATA) or not 0 <= have <= FULL_MASK:
        raise ValueError("TYPE o HAVE inválido")
    if not 0 <= seq < MAX_CHUNKS or len(data) != CHUNK_SIZE:
        raise ValueError("SEQ o tamaño de DATA inválido")
    if kind == STATUS and (seq != 0 or data != ZERO_DATA):
        raise ValueError("STATUS debe tener SEQ y DATA a cero")
    return FRAME.pack(kind | seq, have, data)


def unpack_frame(payload, n=None):
    """Valida sin cambiar el nodo. None significa descartar, no un evento RX."""
    if not isinstance(payload, (bytes, bytearray)) or len(payload) != FRAME.size:
        return None
    tag, have, data = FRAME.unpack(payload)
    kind, seq = tag & 0xE0, tag & 0x1F
    if kind not in (STATUS, DATA):
        return None
    if kind == DATA:
        if n is not None and seq >= n:
            return None
        if seq == 0:
            try:
                n_from_header(data)
            except ValueError:
                return None
    # 5.2 exige aceptar los demás campos: no añadir requisitos sobre HAVE,
    # ni rechazar un STATUS por su SEQ o por sus bytes DATA (se ignoran).
    mask = FULL_MASK if n is None else (1 << n) - 1
    return kind, seq, have & mask, data


class Node:
    """Un bucle secuencial; radio aporta RX y DONE, el nodo mantiene dos plazos."""

    def __init__(self, radio, source=None, output=None, clock=time.monotonic, rng=None):
        self.radio = radio
        self.source = source  # None: receptor; b"": origen de un archivo vacío.
        self.output = Path(output) if output is not None else None
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self.state = STOPPED
        self._reset()

    def _reset(self):
        self.have = self.send = 0
        self.ask = self.complete = False
        self.n = None
        self.chunks = [None] * MAX_CHUNKS
        self.backoff_at = self.ask_at = None

    @property
    def pending(self):
        return self.send != 0 or self.ask

    def _enter(self, state, at):
        self.state = state
        self.backoff_at = (at + self.rng.randint(1, CW) * SLOT
                           if state == BACKOFF else None)

    def _restart_request(self, at):
        self.ask_at = None if self.complete else at + self.rng.uniform(0.5 * T_ASK, 1.5 * T_ASK)

    def _verify(self):
        try:
            reconstruct(self.chunks)
        except ValueError as error:
            logging.warning("Verificación fallida (%s); se pedirán todos los fragmentos", error)
            self.chunks = [None] * MAX_CHUNKS
            self.have = self.send = 0
            self.n = None
            self.complete = False
            self.ask = True
        else:
            self.complete = True
            self.ask = False
            self.ask_at = None
            logging.info("Archivo completo y CRC-32 verificado; el nodo sigue ayudando")

    def _receive(self, frame, at):
        kind, seq, received_have, data = frame
        if kind == DATA:
            bit = 1 << seq
            if not self.have & bit:
                self.chunks[seq] = data
                self.have |= bit
                self.send |= bit
                self._restart_request(at)
                if seq == 0:
                    self.n = n_from_header(data)
                    mask = (1 << self.n) - 1
                    self.have &= mask
                    self.send &= mask
                    self.chunks[self.n:] = [None] * (MAX_CHUNKS - self.n)
                if self.n is not None and self.have == (1 << self.n) - 1:
                    self._verify()
            else:
                self.send &= ~bit  # Supresión; después, y solo después, reparación.
        mask = FULL_MASK if self.n is None else (1 << self.n) - 1
        self.send |= self.have & ~received_have & mask

    def handle(self, event, frame=None, at=None):
        """Tabla 4. at es el instante del evento, en el reloj monotónico."""
        at = self.clock() if at is None else at
        if event == STOP and self.state != STOPPED:
            try:
                if self.complete and self.output is not None:
                    self.output.write_bytes(reconstruct(self.chunks))
                    logging.info("Archivo guardado en %s", self.output)
                elif not self.complete:
                    logging.warning("STOP: recepción incompleta; no se escribe el archivo")
            finally:
                self.ask_at = None
                self._enter(STOPPED, at)
                self.radio.stop()
        elif event == GO and self.state == STOPPED:
            self._reset()
            if self.source is not None:
                chunks = fragment(self.source)
                self.n = len(chunks)
                self.chunks[:self.n] = chunks
                self.have = self.send = (1 << self.n) - 1
                self.complete = True
            else:
                self._restart_request(at)
            self.radio.flush_rx()
            self.radio.listen()
            self._enter(BACKOFF if self.pending else IDLE, at)  # M1
        elif event == RX and self.state in (IDLE, BACKOFF):
            decoded = unpack_frame(frame, self.n)
            if decoded is None:
                return False
            self._receive(decoded, at)  # R1 antes de evaluar P.
            self._enter(BACKOFF if self.pending else IDLE, at)  # M1 / M2
        elif event == ASK and self.state != STOPPED and not self.complete:
            self.ask = True
            self._restart_request(at)  # R2: no cambia un backoff ya activo.
            if self.state == IDLE:
                self._enter(BACKOFF, at)  # M1
        elif event == EXP and self.state == BACKOFF:
            if self.send:
                seq = (self.send & -self.send).bit_length() - 1
                payload = pack_frame(DATA, self.have, seq, self.chunks[seq])
                self.send &= ~(1 << seq)
            else:
                payload = pack_frame(STATUS, self.have)
            self.ask = False  # DATA también anuncia nuestras necesidades.
            self.radio.start_tx(payload)  # R3; el controlador deja de escuchar.
            self._enter(TX, at)
        elif event == DONE and self.state == TX:
            self.radio.listen()
            self._enter(BACKOFF if self.pending else IDLE, at)  # M3
        else:
            return False
        return True

    def poll(self):
        """Procesa como máximo un evento. La finalización TX viene del controlador."""
        if self.state == STOPPED:
            return
        if self.state == TX:
            end = self.radio.tx_done()
            if end is not None:
                self.handle(DONE, at=end)
                return
        else:
            received = self.radio.receive()
            if received is not None:
                payload, end = received
                if self.handle(RX, payload, at=end):
                    return
                # Una trama descartada no es RX ni debe impedir un ASK/EXP vencido.
        now = self.clock()
        timers = [(deadline, event) for deadline, event in
                  ((self.ask_at, ASK), (self.backoff_at, EXP)) if deadline is not None]
        if timers:
            deadline, event = min(timers)
            if now >= deadline:
                self.handle(event, at=now)

    def delay(self, maximum=0.001):
        """Espera del bucle, no un tercer temporizador del protocolo."""
        now = self.clock()
        remaining = [d - now for d in (self.ask_at, self.backoff_at) if d is not None]
        return max(0.0, min([maximum] + remaining))
