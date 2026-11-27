"""Short Range Individual: the QM transfer, scored on time, our two boxes alone.

Profile: QM's channel 74 and PA min (10 mW e.i.r.p. on a fixed channel), but **2 Mbps** (27-Nov-26,
Santiago) for a shorter airtime. 2 Mbps costs ~10 dB of receiver sensitivity against 250 kbps, so the
link-budget margin at 70 m drops from ~+26 dB to roughly +15 dB: check it at distance (T4/T5).
configs/sri.json carries the same values and wins over this profile.
"""

from .. import p2p
from .qm import PROFILE as QM_PROFILE

PROFILE = {**QM_PROFILE, "data_rate": "2m"}


def run(config: dict) -> bool:
    return p2p.run(config, PROFILE, "SRI")
