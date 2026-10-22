"""Carrega config/niches.yaml aplicando merge profundo de `defaults` em cada nicho."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, create_model

from src.config.models import AppConfig, Niche, NicheSettings

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "niches.yaml"
SCHEMA_PATH = ROOT / "config" / "niches.schema.json"

SETTINGS_KEYS = set(NicheSettings.model_fields)
# Listas que o nicho SOMA às dos defaults em vez de substituir.
UNION_LIST_KEYS = {"blocked_categories"}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = deep_merge(current, value)
        elif key in UNION_LIST_KEYS and isinstance(current, list) and isinstance(value, list):
            result[key] = current + [v for v in value if v not in current]
        else:
            result[key] = copy.deepcopy(value)
    return result


def build_config(raw: dict[str, Any]) -> AppConfig:
    raw = copy.deepcopy(raw)
    defaults = raw.get("defaults") or {}
    niches = []
    for entry in raw.get("niches") or []:
        overrides = {k: entry.pop(k) for k in list(entry) if k in SETTINGS_KEYS}
        entry["settings"] = deep_merge(defaults, overrides)
        niches.append(entry)
    raw["niches"] = niches
    return AppConfig.model_validate(raw)


def load_config(path: Path | str | None = None) -> AppConfig:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return build_config(raw)


def _input_schema_model() -> type[BaseModel]:
    """Modelo só para o JSON Schema: o nicho aceita os campos de `defaults` como override."""
    niche_fields: dict[str, Any] = {}
    for name, field in Niche.model_fields.items():
        if name != "settings":
            niche_fields[name] = (field.annotation, field)
    for name, field in NicheSettings.model_fields.items():
        niche_fields[name] = (field.annotation | None, None)
    niche_input = create_model("NicheInput", __config__=ConfigDict(extra="forbid"), **niche_fields)
    return create_model(
        "NichesFile",
        __config__=ConfigDict(extra="forbid"),
        version=(Literal[1], ...),
        global_=(AppConfig.model_fields["global_"].annotation, None),
        defaults=(NicheSettings, ...),
        niches=(list[niche_input], ...),
    )


def generate_schema() -> dict[str, Any]:
    schema = _input_schema_model().model_json_schema(by_alias=True)
    props = schema.get("properties", {})
    if "global_" in props:
        props["global"] = props.pop("global_")
    schema["title"] = "Garimpo niches.yaml"
    return schema


def write_schema(path: Path = SCHEMA_PATH) -> None:
    path.write_text(json.dumps(generate_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
