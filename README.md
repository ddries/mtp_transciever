# mtp_transciever

MTP F26 Team C: one program for every competition mode, on a Raspberry Pi 3 A+ with an Ebyte
E01-ML01SP4 (nRF24L01+ with PA/LNA) on the SP4 breakout. Python 3.13 on the Pi (3.11 or newer).

```sh
$ python main.py                 # mode from config.json ("mode", default qm)
$ python main.py --mode nm       # or choose it on the command line
```

## Layout

| Path | What |
|---|---|
| `main.py` | Launcher: reads `config.json`, picks the mode, runs it |
| `mtp/hardware.py` | How the breakout is wired (CE GPIO 22, CSN spidev0.0), SPI speed, legal PA level |
| `mtp/usb.py` | Picks the file to send on the stick (largest `.txt`, skips Windows/macOS leftovers) |
| `mtp/codec.py` | zlib stream out, checked inflate and safe save of `output.txt` |
| `mtp/p2p.py` | Point-to-point transfer with hardware ACK (QM, SRI, MRM) |
| `mtp/modes/qm.py`, `sri.py`, `mrm.py` | One file per mode: its radio profile, then `p2p.run` |
| `mtp/modes/nm/` | Network Mode, NMP-1, from `sofiavaleero/MTP-Protocol-NM` (its own README, in Spanish) |
| `tests/` | `test_transfer`, `test_usb`, `test_modes`, `test_nmp` (no hardware needed) |

| Mode | Protocol | Radio profile (default) |
|---|---|---|
| `qm` Quick Mode | point to point, one file | channel 74, 250 kbps, PA min (10 mW e.i.r.p.) |
| `sri` Short Range Individual | same as QM | same as QM |
| `mrm` Mid Range Multiple | same as QM for now | same as QM: the 10 mW fixed-channel fallback. Frequency hopping at 20 dBm (the plan, D-R6) is not written yet |
| `nm` Network Mode | NMP-1: broadcast, relay, repair by HAVE bitmaps | NMP-1: channel 79, 1 Mbps, no auto-ACK; PA min |

To add or change a mode, edit its file in `mtp/modes/`; shared code stays in `mtp/`.

## Configuration

Install the libraries (`python -m pip install -r requirements.txt`), copy `config.example.json` to
`config.json` and fill it in:

| Key | Meaning |
|---|---|
| `mode` | `qm`, `sri`, `mrm` or `nm` (default `qm`); `--mode` overrides it |
| `usb_device` | The stick's folder: `/mnt/usb` on our Pis, `E:/` on Windows, `/Volumes/<name>` on macOS |
| `tx_rx_mode` | `tx` sends the stick's file (in NM: the source node); `rx` receives (in NM: a relay node) |
| `address` | QM/SRI/MRM: the 5-character link address, the same on both boxes (NM has its own) |
| `compression` | `true` (default) or `false`, a JSON boolean |
| `spi_hz` | SPI clock, default 4000000 (pyrf24's own 10 MHz is too fast for jumper wires) |
| `channel`, `data_rate`, `pa_level` | Optional overrides of the mode's profile (QM/SRI/MRM; NM takes only `pa_level`). Channel 0-83, `250k`/`1m`/`2m`, `min`/`low`/`high`/`max`. With the SP4 only `min` stays under 10 mW e.i.r.p. on a fixed channel; the others are for a pigtail into an attenuator only. Both boxes must match |

In RX mode the received file is saved as `output.txt` in the USB device. In NM every node writes
`output.txt` at STOP (Ctrl+C or SIGTERM) if its copy is complete and its CRC-32 checks.

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

Timing (`mtp/p2p.py`, QM/SRI/MRM): the transmitter keeps retrying one packet for up to 30 s
(`SEND_TIMEOUT_S`) before it gives up, so a person walking between the boxes does
not end the transfer. Once a transfer has started, the receiver gives up after
35 s without a valid packet (`RECEIVE_TIMEOUT_S`) instead of waiting forever. After
the last packet it keeps listening for 0.5 s, so a retransmitted last packet is
still ACKed.

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
$ .venv/bin/python -m unittest discover -s tests -t .     # all 50 tests, no radio needed
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
Run the tests with `discover -s tests -t .` as above, or one file: `python -m unittest tests/test_nmp.py`.
