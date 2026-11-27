"""Quick Mode: one point-to-point transfer, transmitter reads the stick, receiver writes output.txt.

Profile TEAM_250K (radio/DECISIONS.md D-R1b, D-R4): RF channel 74 (2474 MHz), 250 kbps for the best
sensitivity, PA min = <= 10 mW e.i.r.p. on a fixed channel. Any key in config.json overrides it.
"""

from .. import p2p

PROFILE = {"channel": 74, "data_rate": "250k", "pa_level": "min"}


def run(config: dict) -> bool:
    return p2p.run(config, PROFILE, "QM")
