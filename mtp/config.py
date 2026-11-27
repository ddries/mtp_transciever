import json
from pathlib import Path

def load_config(directory: Path) -> dict:
    path = directory / "config.json"
    with open(path, encoding="utf-8") as file:
        return json.load(file)