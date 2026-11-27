"""Short Range Individual: the QM transfer, scored on time, our two boxes alone.

Same profile as QM (TEAM_250K: channel 74, 250 kbps, PA min). The 16-Oct review kept SRI on the
10 mW fixed channel: +26 dB margin at 70 m and no hop-sync dependency.
"""

from .. import p2p
from .qm import PROFILE as QM_PROFILE

PROFILE = dict(QM_PROFILE)


def run(config: dict) -> bool:
    return p2p.run(config, PROFILE, "SRI")
