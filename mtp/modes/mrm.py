"""Mid Range Multiple: the point-to-point transfer at 260 m while the other teams transmit too.

The plan (D-R6) is adaptive frequency hopping with listen-before-talk at up to 20 dBm e.i.r.p.
(TEAM_FHSS: 37 channels, 30 ms slots); it is NOT implemented in this Python code yet. Until then
MRM runs on the legal 10 mW fixed-channel fallback (D-R4, our channel 74), with ~+3 dB of margin
at 260 m in the link budget: test the distance before relying on it.
"""

from .. import p2p
from ..logger import log
from .qm import PROFILE as QM_PROFILE

PROFILE = dict(QM_PROFILE)


def run(config: dict) -> bool:
    log("MRM: fixed-channel 10 mW fallback (no frequency hopping yet)")
    return p2p.run(config, PROFILE, "MRM")
