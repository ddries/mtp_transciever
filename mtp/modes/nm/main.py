"""GO con Intro (o --go); STOP con Ctrl+C. No se sale al completar el archivo."""

import argparse
import logging
import signal
import time
from pathlib import Path

from .nmp import GO, STOP, STOPPED, MAX_FILE, Node
from .radio import NRF24Radio, UDPRadio


def stop_signal(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description="NMP-1: distribución de un archivo binario")
    parser.add_argument("--input", type=Path, help="Archivo de origen; omitir en un receptor")
    parser.add_argument("--output", type=Path, default=Path("received.bin"), help="Archivo a escribir en STOP")
    parser.add_argument("--radio", choices=("nrf24", "udp"), default="nrf24")
    parser.add_argument("--ce", type=int, help="GPIO BCM conectado a CE del nRF24 (comprobar cableado)")
    parser.add_argument("--csn", type=int, help="Selector SPI de CSN: 10*bus+CS; no es el número GPIO")
    parser.add_argument("--pa", choices=("min", "low", "high", "max"), help="Potencia elegida según módulo/antena")
    parser.add_argument("--spi-hz", type=int, help="Velocidad SPI en Hz (por defecto la de pyrf24, 10 MHz)")
    parser.add_argument("--port", type=int, default=9000, help="Puerto UDP local")
    parser.add_argument("--peer", type=int, default=9001, help="Puerto UDP del otro proceso local")
    parser.add_argument("--go", action="store_true", help="GO inmediato sin esperar Intro")
    args = parser.parse_args(argv)
    if args.radio == "nrf24":
        if args.ce is None or args.csn is None or args.pa is None:
            parser.error("En la Raspberry Pi indica --ce, --csn y --pa según tu hardware; consulta README.md")
        if not 0 <= args.ce < 65535 or not 0 <= args.csn < 65535:
            parser.error("CE y CSN deben ser enteros entre 0 y 65534")
    if args.radio == "udp" and (not 1 <= args.port <= 65535 or not 1 <= args.peer <= 65535
                                or args.port == args.peer):
        parser.error("UDP requiere dos puertos distintos entre 1 y 65535")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    node = radio = None
    result = 0
    previous_handlers = {}
    try:
        source = None
        if args.input is not None:
            with args.input.open("rb") as stream:
                source = stream.read(MAX_FILE + 1)  # Detecta truncamiento sin cargar archivos enormes.
        radio = (UDPRadio(args.port, args.peer) if args.radio == "udp"
                 else NRF24Radio(args.ce, args.csn, args.pa, args.spi_hz))
        node = Node(radio, source, args.output)
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            signum = getattr(signal, name, None)
            if signum is not None:
                previous_handlers[signum] = signal.signal(signum, stop_signal)
        if args.radio == "udp":
            logging.info("Prueba UDP local: puerto %d -> %d; no usa una radio física", args.port, args.peer)
        if not args.go:
            input("Pulsa Intro para GO; Ctrl+C para STOP. ")
        node.handle(GO)
        logging.info("GO; Ctrl+C envía STOP y guarda el archivo si está completo")
        while node.state != STOPPED:
            node.poll()
            time.sleep(node.delay())
    except (KeyboardInterrupt, EOFError):
        logging.info("STOP")
    except (OSError, RuntimeError) as error:
        logging.error("%s", error)
        result = 1
    finally:
        try:
            if node is not None:
                node.handle(STOP)
        except OSError as error:
            logging.error("No se pudo guardar la salida: %s", error)
            result = 1
        finally:
            if radio is not None:
                radio.close()
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
