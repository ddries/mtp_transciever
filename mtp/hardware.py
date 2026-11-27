"""How the Ebyte E01-ML01SP4 breakout is wired to the Raspberry Pi 3 A+. Shared by every mode.

Breakout J1 -> Pi header: CE -> pin 15 (GPIO 22), CSN -> pin 24 (GPIO 8 = SPI0 CE0, /dev/spidev0.0),
SCK -> 23, MOSI -> 19, MISO -> 21, IRQ -> pin 18 (GPIO 24, unused so far). README.md has the table.
"""

CE_PIN = 22                 # BCM numbering
CSN_PIN = 0                 # pyrf24 on SPIDEV: 10 * bus + chip select -> /dev/spidev0.0
DEFAULT_SPI_HZ = 4_000_000  # pyrf24 defaults to 10 MHz; jumper wires to the breakout want less
MAX_CHANNEL = 83            # 2400 + 83 MHz; higher channels leave the 2400-2483.5 MHz band

# The SP4 has a PA after the nRF24 (~+20 dB, to be measured in T0). On one fixed channel the
# legal limit is 10 mW e.i.r.p. (CNAF UN-85 b), so over the air only "min" (-18 dBm chip) is
# allowed. 20 dBm needs frequency hopping with listen-before-talk (UN-85 a, D-R6). The other
# levels are for a pigtail into an attenuator only.
PA_NAMES = ("min", "low", "high", "max")
LEGAL_FIXED_CHANNEL_PA = "min"
