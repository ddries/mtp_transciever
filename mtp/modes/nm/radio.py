"""Adaptadores para pyrf24 0.6.0 en Raspberry Pi/Linux y para UDP local.

La API de abajo es nuestra, no la de una biblioteca nRF24L01 concreta:
listen/stop, flush_rx, receive -> (bytes, fin RX) o None,
start_tx(bytes), tx_done -> fin TX o None, close. Tiempos: time.monotonic().
Un controlador físico debe aportar DONE desde TX_DS/IRQ, no estimarlo con sleep.
"""

import socket
import sys
import time

# Tabla 1 del PDF. La potencia depende del módulo, PA y antena documentados.
CHANNEL = 79
ADDRESS = bytes.fromhex("1C9B4E9B1C")
DATA_RATE = 1_000_000
CRC_BYTES = 2
PAYLOAD_SIZE = 32
AUTO_ACK = AUTO_RETRANSMIT = DYNAMIC_PAYLOAD = False


class NRF24Radio:
    """CE usa numeración BCM; CSN es 10 * bus SPI + chip select con SPIDEV."""

    def __init__(self, ce, csn, pa_level, spi_speed=None):
        if sys.platform != "linux":
            raise RuntimeError("La radio nRF24 requiere Linux en la Raspberry Pi; en este PC usa --radio udp")
        try:
            import pyrf24
        except ImportError as error:
            raise RuntimeError("Instala en la Raspberry Pi: python -m pip install pyrf24==0.6.0") from error
        if pyrf24.RF24_DRIVER != "SPIDEV":
            raise RuntimeError("Este adaptador requiere pyrf24 con backend SPIDEV (el distribuido por PyPI)")
        levels = {"min": pyrf24.RF24_PA_MIN, "low": pyrf24.RF24_PA_LOW,
                  "high": pyrf24.RF24_PA_HIGH, "max": pyrf24.RF24_PA_MAX}
        if pa_level not in levels:
            raise ValueError("Potencia inválida: usa min, low, high o max según el módulo")
        # spi_speed en Hz; None deja el valor de pyrf24 (10 MHz). Team C usa 4 MHz con cables.
        self.device = pyrf24.RF24(ce, csn) if spi_speed is None else pyrf24.RF24(ce, csn, spi_speed)
        self.tx_ds = int(pyrf24.RF24_TX_DS)
        self.tx_df = int(pyrf24.RF24_TX_DF)
        self.listening = self.sending = False
        if not self.device.begin():
            raise RuntimeError("No se detecta el nRF24: comprueba SPI, CE/CSN, alimentación y permisos GPIO/SPI")
        self.device.stop_listening(ADDRESS)
        self.device.channel = CHANNEL
        self.device.address_width = len(ADDRESS)
        self.device.set_auto_ack(AUTO_ACK)
        self.device.set_retries(0, 0)
        self.device.dynamic_payloads = DYNAMIC_PAYLOAD
        self.device.ack_payloads = False
        self.device.payload_size = PAYLOAD_SIZE
        self.device.data_rate = pyrf24.RF24_1MBPS
        self.device.crc_length = pyrf24.RF24_CRC_16
        self.device.pa_level = levels[pa_level]
        self.device.toggle_all_pipes(False)
        self.device.open_rx_pipe(1, ADDRESS)
        self.stop()  # No escucha ni transmite hasta GO.

    def listen(self):
        self.device.power = True
        self.device.listen = True
        self.listening = True

    def stop(self):
        if self.device is not None:
            self.device.ce_pin(False)
            self.device.power = False
            self.device.flush_tx()
            self.device.flush_rx()
            self.device.clear_status_flags()
        self.listening = self.sending = False

    def flush_rx(self):
        self.device.flush_rx()

    def receive(self):
        if self.listening and self.device.available():
            end = time.monotonic()  # Momento de detección por sondeo, antes de leer por SPI.
            return bytes(self.device.read(PAYLOAD_SIZE)), end
        return None

    def start_tx(self, payload):
        if len(payload) != PAYLOAD_SIZE:
            raise ValueError("El payload nRF24 debe ocupar 32 bytes")
        self.device.stop_listening()
        self.listening = False
        self.device.flush_tx()
        self.device.clear_status_flags()  # Elimina TX_DS de una transmisión anterior.
        # False es multicast: no habilitar EN_DYN_ACK ni W_TX_PAYLOAD_NO_ACK.
        # Autoack ya está desactivado globalmente. start_write no espera al final TX.
        if not self.device.start_write(payload, False):
            raise RuntimeError("No se pudo cargar la trama en el FIFO TX")
        self.sending = True

    def tx_done(self):
        if self.sending:
            flags = self.device.update()  # Lee STATUS fresco, sin borrar eventos nuevos.
            if flags & self.tx_df:
                self.stop()
                raise RuntimeError("MAX_RT inesperado: revisa que autoack y retransmisión estén desactivados")
            if flags & self.tx_ds:
                end = time.monotonic()
                self.device.ce_pin(False)
                self.device.clear_status_flags()
                self.sending = False
                return end
        return None

    def close(self):
        self.stop()
        self.device = None


class UDPRadio:
    """Dos puertos de localhost; envía únicamente los 32 bytes NMP, sin cabeceras propias."""

    def __init__(self, port, peer):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(("127.0.0.1", port))
            self.socket.setblocking(False)
        except OSError:
            self.socket.close()
            raise
        self.peer = ("127.0.0.1", peer)
        self.listening = False
        self.sent_at = None

    def listen(self):
        self.listening = True

    def stop(self):
        self.listening = False
        self.sent_at = None

    def flush_rx(self):
        while True:
            try:
                self.socket.recv(33)
            except (BlockingIOError, ConnectionResetError, ConnectionRefusedError):
                return

    def receive(self):
        if self.listening:
            try:
                payload = self.socket.recv(33)  # 33 permite rechazar datagramas demasiado largos.
            except (BlockingIOError, ConnectionResetError, ConnectionRefusedError):
                return None
            return payload, time.monotonic()
        return None

    def start_tx(self, payload):
        self.listening = False
        self.socket.sendto(payload, self.peer)
        self.sent_at = time.monotonic()

    def tx_done(self):
        end = self.sent_at
        self.sent_at = None
        if end is not None:
            self.flush_rx()  # Este transporte tampoco recibe durante TX.
        return end  # Confirma sendto, no simula el tiempo de aire de un nRF24.

    def close(self):
        self.socket.close()
