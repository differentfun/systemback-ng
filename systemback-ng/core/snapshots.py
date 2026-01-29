import json
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .utils import sanitize_label, ensure_dir


@dataclass
class Snapshot:
    id: str
    path: Path
    label: str
    created: float
    base: str | None


def list_snapshots(cfg: Config) -> list[Snapshot]:
    snaps: list[Snapshot] = []
    if not cfg.snapshots_dir.exists():
        return snaps
    for item in sorted(cfg.snapshots_dir.iterdir()):
        if item.is_file() and item.name.endswith(".tar.zst"):
            snaps.append(
                Snapshot(
                    id=item.name,
                    path=item,
                    label="",
                    created=item.stat().st_mtime,
                    base=None,
                )
            )
        elif item.is_dir():
            meta = item / "metadata.json"
            if meta.exists():
                data = json.loads(meta.read_text())
                snaps.append(
                    Snapshot(
                        id=data.get("id", item.name),
                        path=item,
                        label=data.get("label", ""),
                        created=data.get("created", 0),
                        base=data.get("base"),
                    )
                )
    return snaps


def latest_snapshot(cfg: Config) -> Snapshot | None:
    snaps = list_snapshots(cfg)
    if not snaps:
        return None
    return sorted(snaps, key=lambda s: s.created)[-1]


def create_snapshot_dir(cfg: Config, label: str, base: Snapshot | None) -> Snapshot:
    ts = time.strftime("%Y%m%d-%H%M%S")
    label = sanitize_label(label)
    snap_id = f"{ts}_{label}" if label and label != "auto" else ts
    path = cfg.snapshots_dir / snap_id
    ensure_dir(path)

    snap = Snapshot(
        id=snap_id,
        path=path,
        label=label,
        created=time.time(),
        base=base.id if base else None,
    )
    return snap


def write_snapshot_metadata(snap: Snapshot) -> None:
    meta = {
        "id": snap.id,
        "label": snap.label,
        "created": snap.created,
        "base": snap.base,
    }
    (snap.path / "metadata.json").write_text(json.dumps(meta, indent=2))
