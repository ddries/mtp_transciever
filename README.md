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

The transmitter compresses the original file bytes with zlib by default. When
that does not make the data smaller (random or already-compressed files, tiny or
empty files) it still sends a zlib stream, made of stored blocks (level 0,
11 bytes more). So every transfer carries the zlib Adler-32 checksum. The
receiver decodes the stream and checks it before replacing `output.txt`: a
corrupted, truncated or spliced transfer is rejected and the old `output.txt`
stays. This preserves binary data, text encodings and line endings.

For compressed transfers, update both radios. To send to an older receiver,
set `"compression": false` on the transmitter (a JSON boolean, without quotes):
that sends raw bytes, which have no end-to-end check. The updated receiver also
accepts raw transfers from older transmitters.

Each packet still carries up to 28 data bytes after a four-byte big-endian
header. Bit 31 is set in every packet of a compressed transfer. The low 31
bits count the packets remaining after this one.

Timing (`radio.py`): the transmitter keeps retrying one packet for up to 30 s
(`SEND_TIMEOUT_S`) before it gives up, so a person walking between the boxes does
not end the transfer. Once a transfer has started, the receiver gives up after
35 s without a valid packet (`RECEIVE_TIMEOUT_S`) instead of waiting forever. After
the last packet it keeps listening for 0.5 s, so a retransmitted last packet is
still ACKed.

Run the transciever,

```sh
$ python main.py
```

## Bench test with the SP4 breakout (Raspberry Pi 3 A+)

Wiring, breakout J1 (pin 1 = square pad) to the Pi header:

| J1 | Signal | Pi header pin (BCM) |
|---|---|---|
| 1 | GND | 6 (any GND), also the 3.3 V supply's GND |
| 2 | VCC | 3.3 V: the Pi's pin 1 is fine at PA `min` (bench tests); a 3.3 V supply >= 150 mA above that. Never pin 17 (next to CE) |
| 3 | CE | 15 (GPIO 22) |
| 4 | CSN | 24 (GPIO 8, SPI0 CE0) |
| 5 | SCK | 23 (GPIO 11) |
| 6 | MOSI | 19 (GPIO 10) |
| 7 | MISO | 21 (GPIO 9) |
| 8 | IRQ | 18 (GPIO 24), not used by this program |

The SP4's PA draws ~120 mA in bursts; never feed it more than 3.6 V. Antenna (or pigtail) on the IPEX
plug before powering it. After soldering a breakout, beep every neighbouring pair of J1 pins with the power
off: none may beep. (27-Nov: a CE-CSN bridge on C1 made CE follow CSN, so the radio never sent or received.)

On the Pi (SPI already enabled on our boxes, Python 3.13 has a ready pyrf24 wheel; our two Pis have the
venv in `.venv` inside the repo):

```sh
$ python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
$ ls /dev/spidev0.0
$ .venv/bin/python -m unittest tests/test_transfer.py tests/test_usb.py
```

Our Pis boot without a desktop, so a USB stick is not mounted on its own. `udisksctl` works on the Pi's
own console but is refused over SSH; there use `sudo mount`. Some sticks have no partition table: then
the file system is on `/dev/sda`, not `/dev/sda1` (`lsblk` shows `vfat` on the line that has it).

```sh
$ lsblk -o NAME,SIZE,FSTYPE,LABEL         # find the stick: sda1, or sda itself
$ sudo mount -o uid=$(id -u),gid=$(id -g),umask=022 /dev/sda1 /mnt/usb
$ sync; sudo umount /mnt/usb              # before pulling it out
```

The transmitter sends the largest `.txt` at the top of `usb_device` (it skips `desktop.ini`, `~$` Office lock
files and macOS `._` files). The receiver writes `output.txt` into `usb_device` and replaces one that is there.

Start the receiver first (the transmitter waits up to 30 s for the first ACK).
Plain `python -m unittest` finds no tests: name the files as above.
