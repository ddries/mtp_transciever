# mtp_transciever

Use latest Python version (+3.15).

```sh
$ python --version
Python 3.15.1
```

Install the required libraries:

```sh
$ python -m pip install -r requirements.txt
```

Copy `config.example.json` and remove `.example`: config.example.json -> config.json.
Then, populate configuration. `usb_device` needs to be the name of your USB drive in your computer, e.g.,
- `E:/` under Windows,
- `/Volumes/<USB Name>` under macOS,
- `/media/mtp_team-c2/<USB Name>` in Raspberry Pi.

`address` is the 5 character address of the link, the TX and the RX need to use the same one.
`channel` is optional (0-83, default 76; 2400 + channel MHz, higher channels are outside the band).
`pa_level` is optional (`min`, `low`, `high`, `max`; default `min`). With the Ebyte E01-ML01SP4 only `min`
stays under 10 mW e.i.r.p. on a fixed channel; the others are for a pigtail into an attenuator only.
`data_rate` is optional (`250k`, `1m`, `2m`; default `250k`, the best sensitivity). Both radios must match.
`spi_hz` is optional (default 4000000; pyrf24's own default is 10 MHz, too fast for jumper wires).

For example,

```json
{
    "usb_device": "/Volumes/USB2",
    "tx_rx_mode": "tx",
    "address": "1Node",
    "channel": 76,
    "compression": true,
    "pa_level": "min",
    "data_rate": "250k"
}
```

In RX mode the received file is saved as `output.txt` in the USB device.

The transmitter tries zlib compression on the original file bytes by default.
It sends compressed data only when that reduces the payload size. The receiver
automatically decodes it and checks the zlib checksum before replacing
`output.txt`. This preserves binary data, text encodings and line endings.

For compressed transfers, update both radios. To send to an older receiver,
set `"compression": false` on the transmitter. The updated receiver also accepts
ordinary raw transfers from older transmitters.

Each packet still carries up to 28 data bytes after a four-byte big-endian
header. Bit 31 is set in every packet of a compressed transfer. The low 31
bits count the packets remaining after this one. An empty file uses one raw
packet with a zero count.

Run the transciever,

```sh
$ python main.py
```

## Bench test with the SP4 breakout (Raspberry Pi 3 A+)

Wiring, breakout J1 (pin 1 = square pad) to the Pi header:

| J1 | Signal | Pi header pin (BCM) |
|---|---|---|
| 1 | GND | 6 (any GND), also the 3.3 V supply's GND |
| 2 | VCC | **3.3 V bench supply or LDO, >= 150 mA** (or the J2 bench pins); not the Pi's 3V3 pin |
| 3 | CE | 15 (GPIO 22) |
| 4 | CSN | 24 (GPIO 8, SPI0 CE0) |
| 5 | SCK | 23 (GPIO 11) |
| 6 | MOSI | 19 (GPIO 10) |
| 7 | MISO | 21 (GPIO 9) |
| 8 | IRQ | 18 (GPIO 24), not used by this program |

The SP4's PA draws ~120 mA in bursts; never feed it more than 3.6 V. Antenna (or pigtail) on the IPEX
plug before powering it.

On the Pi (SPI already enabled on our boxes, Python 3.13 has a ready pyrf24 wheel):

```sh
$ python3 -m venv ~/venv && ~/venv/bin/pip install -r requirements.txt
$ ls /dev/spidev0.0
$ ~/venv/bin/python -m unittest tests/test_transfer.py
```

Our Pis boot without a desktop, so a USB stick is not mounted on its own:

```sh
$ lsblk                                   # find the stick, e.g. sda1
$ udisksctl mount -b /dev/sda1            # mounts at /media/$USER/<label>
$ udisksctl unmount -b /dev/sda1          # before pulling it out
```

Start the receiver first: the transmitter gives up on the first packet after ~2 s.
Run the tests with `python -m unittest tests/test_transfer.py` (plain `python -m unittest` finds none).
