import yaml
import re
from pathlib import Path

class WrapConfig:
    CONFIG = {}

    @classmethod
    def load(cls):
        configPath = Path(__file__).parent / "application.yml"
        if not configPath.exists():
            raise FileNotFoundError(f"Config file not found at {configPath}")
        with open(configPath, "r") as f:
            raw_config = yaml.safe_load(f)
        cls.CONFIG = cls._interpolate(raw_config)

    @classmethod
    def _interpolate(cls, config, context=None):
        if context is None:
            context = config  # top-level context

        if isinstance(config, dict):
            return {k: cls._interpolate(v, context) for k, v in config.items()}

        elif isinstance(config, list):
            return [cls._interpolate(v, context) for v in config]

        elif isinstance(config, str):
            # Replace ${...} with corresponding values
            pattern = re.compile(r"\$\{([^\}]+)\}")
            while True:
                match = pattern.search(config)
                if not match:
                    break
                key_path = match.group(1)
                replacement = cls._resolve_path(key_path, context)
                config = config.replace(f"${{{key_path}}}", replacement)
            return config

        else:
            return config

    @classmethod
    def _resolve_path(cls, key_path, config):
        keys = key_path.split(".")
        value = config
        for key in keys:
            value = value[key]
        return str(value)

    @classmethod
    def get(cls, key_path, default=None):
        keys = key_path.split("/")
        value = cls.CONFIG
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default