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
`channel` is optional (0-125, default 76).

For example,

```json
{
    "usb_device": "/Volumes/USB2",
    "tx_rx_mode": "tx",
    "address": "1Node",
    "channel": 76,
    "compression": true
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
