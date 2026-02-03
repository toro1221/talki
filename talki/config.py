"""JSON-based persistent settings for Talki."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .platform_utils import get_config_dir


@dataclass
class Config:
    input_device_id: int | None = None
    push_to_talk_key: str = "F9"
    toggle_record_key: str = "F10"
    model_size: str = "base"
    language: str = "en"
    injection_mode: str = "auto"
    transcribe_interval_ms: int = 1500

    _path: Path = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._path is None:
            self._path = get_config_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        path = get_config_dir() / "config.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                data.pop("_path", None)
                cfg = cls(**{k: v for k, v in data.items()
                             if k in cls.__dataclass_fields__})
                cfg._path = path
                return cfg
            except (json.JSONDecodeError, TypeError):
                pass
        cfg = cls()
        cfg._path = path
        cfg.save()
        return cfg

    def save(self):
        data = asdict(self)
        data.pop("_path", None)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))
