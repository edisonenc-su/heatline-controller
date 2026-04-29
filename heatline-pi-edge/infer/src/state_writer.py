import json
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_file(path: Path, default_value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default_value, indent=2), encoding='utf-8')


def read_json(path: Path, default_value):
    ensure_file(path, default_value)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return deepcopy(default_value)


def write_json(path: Path, value):
    ensure_file(path, value)
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def patch_status(path: Path, partial: dict):
    current = read_json(path, {})
    current.update(partial)
    current['updated_at'] = now_iso()
    write_json(path, current)
    return current
