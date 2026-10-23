import copy

import pytest
import yaml
from pydantic import ValidationError

from src.common import secrets
from src.config.loader import DEFAULT_CONFIG_PATH, build_config, deep_merge, generate_schema
from src.config.validate import main as validate_main


def raw_config():
    return yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def test_repo_config_is_valid(config):
    assert [n.id for n in config.niches if n.is_active] == ["casa", "pet"]
    assert config.niche("beauty").status == "candidate"


def test_niche_overrides_merge_with_defaults(config):
    pet = config.niche("pet")
    assert pet.settings.filters.price_min == 15
    assert pet.settings.filters.min_rating == 4.5  # veio dos defaults
    # listas de bloqueio somam, não substituem
    assert "armas" in pet.settings.filters.blocked_categories
    assert "antipulgas" in pet.settings.filters.blocked_categories


def test_deep_merge_replaces_regular_lists():
    merged = deep_merge({"publish_slots": ["08:00"], "a": {"b": 1}}, {"publish_slots": ["09:00"], "a": {"c": 2}})
    assert merged == {"publish_slots": ["09:00"], "a": {"b": 1, "c": 2}}


def test_invalid_niche_id_rejected():
    raw = raw_config()
    raw["niches"][0]["id"] = "Casa Nova"
    with pytest.raises(ValidationError):
        build_config(raw)


def test_unknown_key_rejected():
    raw = raw_config()
    raw["niches"][0]["telegram_token"] = "x"
    with pytest.raises(ValidationError):
        build_config(raw)


def test_duplicate_sub_id_rejected():
    raw = raw_config()
    raw["niches"][1]["tracking"]["sub_id"] = raw["niches"][0]["tracking"]["sub_id"]
    with pytest.raises(ValidationError, match="duplicado"):
        build_config(raw)


def test_enabled_instagram_not_supported_yet():
    raw = raw_config()
    raw["niches"][0]["channels"]["instagram"]["enabled"] = True
    with pytest.raises(ValidationError, match="instagram"):
        build_config(raw)


def test_active_niche_needs_source():
    raw = copy.deepcopy(raw_config())
    niche = raw["niches"][0]
    niche["platforms"] = {}
    niche.pop("manual_offers")
    with pytest.raises(ValidationError, match="sem fonte"):
        build_config(raw)


def test_required_secrets_only_names(config):
    names = secrets.required_secrets(config)
    assert {"TG_CASA_CHAT_ID", "TG_PET_CHAT_ID", "SHOPEE_APP_ID"} <= set(names)
    assert "TG_GERAL_CHAT_ID" not in names  # nicho pausado não exige segredo
    with pytest.raises(secrets.MissingSecretsError) as err:
        secrets.require(names, {})
    assert "DATABASE_URL" in str(err.value)


def test_schema_is_up_to_date():
    import json

    from src.config.loader import SCHEMA_PATH

    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == generate_schema()


def test_validate_cli(capsys):
    assert validate_main([]) == 0
    assert "ativos: casa, pet" in capsys.readouterr().out
    assert validate_main(["--check-secrets"]) in (0, 1)
