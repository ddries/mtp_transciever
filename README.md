# mtp_transciever

MTP F26 Team C: one program for every competition mode, on a Raspberry Pi 3 A+ with an Ebyte
E01-ML01SP4 (nRF24L01+ with PA/LNA) on the SP4 breakout. Python 3.13 on the Pi (3.11 or newer).

```sh
$ .venv/bin/python main.py --mode sri --role rx     # receiving box: start it first
$ .venv/bin/python main.py --mode sri --role tx     # sending box
$ .venv/bin/python main.py --mode nm --role tx      # NM source node (relays: --role rx); Ctrl+C = STOP
```

Each mode's settings are in `configs/<mode>.json`, the same on every box, so nothing needs editing
between runs: choose the mode and this box's role. `--usb /some/folder` uses another stick folder.

## Layout

| Path | What |
|---|---|
| `main.py` | Launcher: `configs/<mode>.json` + optional `config.json` + `--role`/`--usb`, then runs the mode |
| `configs/qm.json`, `sri.json`, `mrm.json`, `nm.json` | Settings of each mode (stick folder, address, radio) |
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
| `sri` Short Range Individual | same as QM | channel 74, **2 Mbps**, PA min (shorter airtime; ~10 dB less sensitivity than 250 kbps) |
| `mrm` Mid Range Multiple | same as QM for now | same as QM: the 10 mW fixed-channel fallback. Frequency hopping at 20 dBm (the plan, D-R6) is not written yet |
| `nm` Network Mode | NMP-1: broadcast, relay, repair by HAVE bitmaps | NMP-1: channel 79, 1 Mbps, no auto-ACK; PA min |

To add or change a mode, edit its file in `mtp/modes/`; shared code stays in `mtp/`.

## Configuration

Install the libraries (`python -m pip install -r requirements.txt`). Settings are merged, later wins:

1. `configs/<mode>.json`: the mode's settings, in git, the same on both boxes. Change them here.
2. `config.json` (optional, not in git): overrides for one box only, e.g. `{"tx_rx_mode": "tx"}` as
   its usual role (see `config.example.json`), or a test channel. Keep it small: everything in it beats
   the mode file.
3. `--role tx|rx` and `--usb PATH` on the command line.

| Key | Meaning |
|---|---|
| `mode` | `qm`, `sri`, `mrm` or `nm`; `--mode` chooses it (else `mode` in `config.json`, else `qm`) |
| `usb_device` | The stick's folder: `/mnt/usb` on our Pis, `E:/` on Windows, `/Volumes/<name>` on macOS |
| `tx_rx_mode` | `tx` sends the stick's file (in NM: the source node); `rx` receives (in NM: a relay node). Usually `--role` |
| `address` | QM/SRI/MRM: the 5-character link address, the same on both boxes (NM has its own). `TeamC`, not pyrf24's example `1Node`, which other teams may use too |
| `compression` | `true` (default) or `false`, a JSON boolean |
| `spi_hz` | SPI clock, default 4000000 (pyrf24's own 10 MHz is too fast for jumper wires) |
| `channel`, `data_rate`, `pa_level` | The radio profile, in the mode files (QM/SRI/MRM; NM takes only `pa_level`). Channel 0-83, `250k`/`1m`/`2m`, `min`/`low`/`high`/`max`. With the SP4 only `min` stays under 10 mW e.i.r.p. on a fixed channel; the others are for a pigtail into an attenuator only. Both boxes must match |

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

## Competition day: serial console, stick, WiFi off

**Serial console (no network needed).** A CP2102 USB-UART module, 3.3 V logic:

| CP2102 | Pi header |
|---|---|
| GND | pin 9 (GND; pin 6 already carries the breakout's GND) |
| TXD | pin 10 (GPIO 15, RXD) |
| RXD | pin 8 (GPIO 14, TXD) |
| 3V3 / 5V | **not connected** (the Pi has its own supply) |

On the laptop it appears as "Silicon Labs CP210x (COMn)" in Device Manager (Windows) or `/dev/ttyUSB0`
(Linux). Open it at **115200 8N1, no flow control** (PuTTY: Connection type Serial), press Enter and log
in as the box's user. Kernel messages (e.g. a stick being plugged in) also appear there; `sudo dmesg -n 1`
silences them until the next boot.

**The stick.** `tools/install-stick.sh` (once, with sudo) installs `teamc-stick` with a sudo rule that
asks no password for it; then:

```sh
$ sudo teamc-stick mount     # finds the stick (sda1, or sda without a partition table), mounts /mnt/usb
$ sudo teamc-stick status
$ sudo teamc-stick umount    # flush + unmount: then pull the stick
```

Without the install: `sudo bash tools/teamc-stick mount` from the repo (asks the password).

**A run**, receiver first: plug the stick in, run the mode, pull the stick out when it says so.

```sh
$ cd ~/mtp_transciever
$ .venv/bin/python main.py --mode sri        # role from config.json, or --role tx|rx
```

`main.py` mounts the stick before the mode (`sudo teamc-stick mount`; no stick = it stops before the
radio) and unmounts it afterwards, also after a failed transfer or Ctrl+C ("Stick unmounted: you can pull
it out"). This applies when the stick folder is `/mnt/usb` or inside it (NM: `--usb /mnt/usb/nm`, created
if missing). `--keep-mounted` leaves it mounted for the next run; `--no-mount` leaves the stick alone.
Without `tools/install-stick.sh` on that box, sudo asks the password at the start.

**WiFi off** (the rules ban the wireless chip in use; it also takes the box off the network): from the
serial console, `sudo nmcli radio wifi off`. It stays off after a reboot. Back on: `sudo nmcli radio wifi on`.
Doing it over SSH cuts your own session.
