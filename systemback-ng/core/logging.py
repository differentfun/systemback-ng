import logging
from .config import Config


def setup_logging(cfg: Config) -> None:
    handlers = []
    try:
        handlers.append(logging.FileHandler(str(cfg.log_file)))
    except PermissionError:
        pass
    handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
