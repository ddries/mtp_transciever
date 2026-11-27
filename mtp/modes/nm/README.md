# MTP-Protocol-NM — Network Mode

Network Mode del proyecto académico **MTP Fall 2026**: distribuir un archivo de aproximadamente
500 bytes entre Raspberry Pi con nRF24L01, mediante varios saltos y sin conocer la topología.
Referencia: **NMP-1 v1.0, 15/11/2026**, el PDF del equipo. Python 3.10 o posterior.

## Relación con el proyecto principal

Esta carpeta pertenece a `sofiavaleero/MTP-Protocol-NM`. Se ha revisado también
[pabl0-p/MTP-Project, revisión 3367489](https://github.com/pabl0-p/MTP-Project/tree/3367489739d5e8fa70031330ee093d78171faa7b):
contiene `Quick Mode (QM)/`, sus pruebas y el lanzador con botón/USB; en esa revisión no hay Network Mode
ni un selector común de modos. La integración entre repositorios está pendiente.

| Aspecto | Quick Mode actual | Network Mode de esta carpeta |
| --- | --- | --- |
| Programa | `qm_file_sender.py` / `qm_file_receiver.py` | `main.py`, el mismo en todos los nodos |
| Transferencia | Punto a punto, secuencial | Broadcast con relay y reparación por HAVE |
| Cabecera de archivo | 8 bytes, longitud y CRC32 `>II` | 6 bytes, longitud y CRC32 `<HI` |
| Fragmentos | Hasta 32 bytes, payload dinámico | 27 bytes dentro de tramas estáticas de 32 bytes |
| Radio | 2 Mbps, dirección `b"Node1"` | 1 Mbps, canal 79, dirección `0x1C9B4E9B1C` |
| Autoack / retransmisión | Activados, `setRetries(5, 15)` | Desactivados, `set_retries(0, 0)` |
| Finalización local | Comprueba tamaño/CRC y guarda al recibir | Verifica CRC; sigue ayudando; guarda al recibir STOP |

QM usa `radio_hardware.py`, `file_transfer.py` y `file_storage.py`; su `radio.py` es una versión anterior con ACK por software.
El `main.py` de esta carpeta ejecuta únicamente Network Mode.

## Código de Network Mode

`nmp.py` contiene formato, fragmentación y una clase `Node`; `radio.py`, los adaptadores;
`main.py`, rutas y GO/STOP; `test_nmp.py`, pruebas deterministas. El bucle secuencial cede CPU, sin hilos ni `asyncio`.

Se conservan la máquina STOPPED/IDLE/BACKOFF/TX, los bitmaps, R1/R2/R3 y M1/M2/M3 del PDF.
Los dos temporizadores son backoff (1–16 slots de 2 ms) y petición (150–450 ms).
Un CRC fallido limpia fragmentos y N y solicita de nuevo; un nodo completo sigue ayudando.
Los archivos mayores de 858 bytes se truncan con aviso. La escritura parcial opcional no se implementa.

## Prueba local sin hardware

Desde esta carpeta, con Python instalado; no requiere paquetes adicionales:

```console
python -c "from pathlib import Path; Path('entrada.bin').write_bytes(bytes(range(250)) * 2)"
```

En dos terminales distintas, ejecuta receptor y origen:

```console
python main.py --radio udp --port 9001 --peer 9000 --output copia.bin
python main.py --radio udp --port 9000 --peer 9001 --input entrada.bin --output copia_origen.bin
```

**Intro = GO; Ctrl+C = STOP.** `--go` permite arrancar sin esperar Intro.
STOP guarda solo archivos completos y verificados, sustituyendo el destino si existe; una recepción incompleta lo conserva.
Completar no cierra el programa. UDP usa localhost y payloads NMP; no modela alcance ni colisiones RF.
Después de STOP, comprueba los bytes:

```console
python -c "from pathlib import Path; assert Path('copia.bin').read_bytes() == Path('entrada.bin').read_bytes()[:858]; print('Copia exacta')"
```

## Instalación y ejecución en Raspberry Pi

El adaptador usa **`pyrf24==0.6.0`, backend SPIDEV, sobre Linux** ([API](https://pyrf24.readthedocs.io/en/latest/rf24_api.html)).
Activa SPI con `sudo raspi-config` (Interface Options > SPI) y ejecuta en cada Pi, desde Network Mode:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install pyrf24==0.6.0
```

Si falta `venv`, instala `python3-venv`. La [guía oficial](https://pyrf24.readthedocs.io/en/latest/)
explica compilación y selección de gpiochip cuando lo requieran el modelo/SO.

### Datos conocidos y datos que hay que confirmar

| Dato | Evidencia / pendiente |
| --- | --- |
| Plataforma | Raspberry Pi, confirmado por el equipo; modelo y SO pendientes |
| CE | El código QM usa GPIO **22 BCM**; confirmar el cableado de cada Pi |
| CSN | QM usa selector **0**, `/dev/spidev0.0`; confirmar el cable CSN y SPI habilitado |
| Biblioteca | Ambos usan `pyrf24`; NM documenta 0.6.0; confirmar la versión instalada en las Pi |
| Potencia / módulo | QM usa `RF24_PA_LOW` para pruebas; faltan modelo, PA/LNA, antena y alimentación documentados |
| Botón | QM declara GPIO **17 BCM** y arranca TX al pulsarlo; falta definir el GO/STOP físico de NM |
| USB | QM dispone de `usb_source.py`; NM usa rutas explícitas, sin automontaje ni detección de retirada |

Para obtener modelo, SO, dispositivos SPI y versión, ejecuta **en la Pi**:

```sh
cat /proc/device-tree/model
cat /etc/os-release
ls /dev/spidev*
python -c "from importlib.metadata import version; print(version('pyrf24'))"
```

El cableado y módulo se comprueban en el montaje. `--ce` usa BCM; `--csn` es **10 × bus SPI + chip select**:
`/dev/spidev0.0` → 0, `/dev/spidev0.1` → 1, `/dev/spidev1.0` → 10 ([referencia](https://github.com/nRF24/pyRF24/blob/v0.6.0/examples/getting_started.py)).
`--pa` es un nivel del chip, no EIRP medida. Para los 20 dBm EIRP del PDF hay que conocer módulo/PA/antena;
el LOW de pruebas de QM no determina la potencia de competición.

Una vez confirmados, introduce los valores en cada Pi, que puede tener un cableado distinto:

```sh
read -rp "GPIO BCM del cable CE (QM configura 22; confirmar): " CE
read -rp "Selector SPI de CSN (QM configura 0; confirmar): " CSN
read -rp "Nivel de potencia documentado (min/low/high/max): " PA
```

Origen con `entrada.bin` existente; receptor en otra Pi, respectivamente:

```sh
python main.py --radio nrf24 --ce "$CE" --csn "$CSN" --pa "$PA" --input entrada.bin --output copia_origen.bin
python main.py --radio nrf24 --ce "$CE" --csn "$CSN" --pa "$PA" --output copia.bin
```

El directorio de salida debe existir; las rutas pueden apuntar a un USB montado, disponible hasta STOP.
Cada arranque aplica el perfil NM de la tabla, dirección de 5 bytes, CRC de radio de 2 bytes,
`DYNPD=0` y `FEATURE=0`. El fin TX se detecta leyendo TX_DS, sin esperar ACK ni añadir un temporizador.

### Ejecutar Quick Mode existente

En el repositorio principal, dentro de `Quick Mode (QM)`, con `pyrf24` instalado y su cableado comprobado,
ejecuta en la Pi receptora y emisora, respectivamente:

```sh
python qm_file_receiver.py --output copia_qm.bin
python qm_file_sender.py --size 500
```

Para un archivo real, el emisor admite `--file entrada.bin`. El receptor conserva archivos existentes salvo `--overwrite`.
El lanzador con USB/botón se ejecuta con `python qm_button.py --role tx` o `--role rx`;
sus dependencias de GPIO/OLED y su configuración USB están en el README del proyecto principal.

## Pruebas y pendientes de integración

Network Mode, desde esta carpeta; Quick Mode, desde su propia carpeta, respectivamente:

```console
python -m unittest -v
python -m unittest discover -s tests -t . -v
```

Comprobado por software: **22 pruebas NM correctas** y suite QM de **248 casos sin fallos, 1 omitido**
por no poder crear enlaces simbólicos en este entorno Windows. NM cubre 0/500/858 bytes, truncamiento,
formato, desorden, duplicados, N tardío, CRC y recuperación, pérdidas, cadena de tres nodos,
corte/restauración, ayuda de nodos completos y silencio final. El adaptador se prueba con un controlador sustituido.
También se comprobaron sockets UDP reales para 0/500/858 bytes y truncamiento de 1000 a 858 bytes.

Queda pendiente:

- Confirmar la tabla y medir radio real, alimentación/potencia, RX/TX_DS y retrasos SPI/SO/sondeo frente al slot de 2 ms.
- Probar tres Pi en cadena, corte/restauración y copias USB exactas; medir la entrega de 500 bytes dentro de cinco minutos.
- Integrar NM en una carpeta propia del proyecto principal, conservando QM y sus interfaces.
  Cada modo reinicializa su perfil y libera la radio al salir; los dos `radio.py` mantienen importaciones separadas.
- Conectar el GO/STOP físico acordado al bucle secuencial; la pulsación de envío de QM todavía no lo implementa.
- Reutilizar `usb_source.py` y `file_storage.py` al integrar, manteniendo formato NMP y guardado en STOP.
  Comprobar montaje/retirada, permisos y escritura USB real.

La completitud de un nodo solo describe su copia: no demuestra que toda la red haya terminado.
Los cinco minutos son una condición de la competición, no un temporizador NMP de finalización.
Las pruebas de software no certifican alcance, colisiones, interoperabilidad ni funcionamiento del hardware.
