import yaml
from pathlib import Path

class WrapConfig:
    CONFIG = {}

    @classmethod
    def load(cls):
        configPath = Path(__file__).parent / "application.yml"
        if not configPath.exists():
            raise FileNotFoundError(f"Config file not found at {configPath}")
        with open(configPath, "r") as f:
            cls.CONFIG = yaml.safe_load(f)

    @classmethod
    def get(cls, key, default=None):
        return cls.CONFIG.get(key, default)

# Load config on module import
WrapConfig.load()