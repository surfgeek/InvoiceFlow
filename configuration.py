"""Load and validate non-secret application settings from TOML."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


DEFAULT_MODEL = "grok-4.6"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class ModelSettings(SettingsModel):
    name: str = Field(default=DEFAULT_MODEL, min_length=1)
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "low"
    timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)


class BatchSettings(SettingsModel):
    workers: int = Field(default=4, ge=1)


class DollarPolicy(SettingsModel):
    action: Literal["assume", "reject"] = "reject"
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def require_assumed_currency(self):
        if self.action == "assume" and self.currency is None:
            raise ValueError("currency is required when action is assume")
        return self


class CurrencySettings(SettingsModel):
    unqualified_dollar: DollarPolicy = Field(default_factory=DollarPolicy)


class AppSettings(SettingsModel):
    model: ModelSettings = Field(default_factory=ModelSettings)
    batch: BatchSettings = Field(default_factory=BatchSettings)
    currency: CurrencySettings = Field(default_factory=CurrencySettings)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppSettings:
    """Fail before processing on unreadable, malformed, or invalid configuration."""
    try:
        with path.open("rb") as source:
            return AppSettings.model_validate(tomllib.load(source))
    except ValidationError as error:
        details = "; ".join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                            for item in error.errors(include_input=False))
        raise ValueError(f"Invalid configuration: {details}") from error
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot load configuration {path}: {error}") from error
