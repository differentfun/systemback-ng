import configparser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/systemback-ng.conf")
DEFAULT_INCLUDES = Path("/etc/systemback-ng.includes")
DEFAULT_EXCLUDES = Path("/etc/systemback-ng.excludes")


@dataclass
class Config:
    config_path: Path
    includes_path: Path
    excludes_path: Path
    state_dir: Path
    log_file: Path
    snapshots_dir: Path
    live_work_dir: Path
    iso_dir: Path


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    parser = configparser.ConfigParser()
    parser.read(path)

    def get_path(section: str, key: str, default: str) -> Path:
        return Path(parser.get(section, key, fallback=default))

    state_dir = get_path("paths", "state_dir", "/var/lib/systemback-ng")
    snapshots_dir = get_path("paths", "snapshots_dir", str(state_dir / "snapshots"))
    live_work_dir = get_path("paths", "live_work_dir", str(state_dir / "livework"))
    log_file = get_path("paths", "log_file", "/var/log/systemback-ng.log")
    iso_dir = get_path("paths", "iso_dir", str(state_dir / "iso"))

    return Config(
        config_path=path,
        includes_path=Path(parser.get("paths", "includes", fallback=str(DEFAULT_INCLUDES))),
        excludes_path=Path(parser.get("paths", "excludes", fallback=str(DEFAULT_EXCLUDES))),
        state_dir=state_dir,
        log_file=log_file,
        snapshots_dir=snapshots_dir,
        live_work_dir=live_work_dir,
        iso_dir=iso_dir,
    )
