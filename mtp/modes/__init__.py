"""Competition modes. Each module has run(config) -> bool; main.py picks one with "mode".

| Mode | What | Code |
|---|---|---|
| qm  | Quick Mode: one box sends the stick's file to one other box | p2p, TEAM_250K profile |
| sri | Short Range Individual: same transfer, our pair alone | p2p, TEAM_250K profile |
| mrm | Mid Range Multiple: all teams at once | p2p, fixed-channel fallback (hopping: to do) |
| nm  | Network Mode: every node gets the file, relaying, all teams | nm/ (NMP-1, Sofia's code) |
"""

from importlib import import_module

MODES = ("qm", "sri", "mrm", "nm")


def run(mode: str, config: dict) -> bool:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    # Imported on demand: a mode's radio code (and pyrf24) loads only when that mode runs
    return import_module(f".{mode}", __name__).run(config)
