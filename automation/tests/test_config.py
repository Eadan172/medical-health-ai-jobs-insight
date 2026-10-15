from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsinsight.config import (
    Config,
    ConfigError,
    LLMSettings,
    OutputSettings,
    ScheduleSettings,
    SourceSettings,
    load_config,
    save_overrides,
)

TOML = """
log_level = "debug"

[schedule]
mode = "cron"
cron = "30 */6 * * 1-5"
timezone = "UTC"

[llm]
provider = "deepseek"
model = "deepseek-chat"
api_key = "${TEST_LLM_KEY}"

[[sources]]
name = "seed"
type = "fixture"
path = "data/seed.json"

[[sources]]
name = "gateway"
type = "json_api"
urls = ["https://example.com/api?page={page}"]

[output]
data_dir = "out/data"
state_dir = "out/state"
"""


def write_config(tmp_path: Path, text: str = TOML, name: str = "config.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_load_toml_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_LLM_KEY", "sk-from-env")
    config = load_config(write_config(tmp_path))

    assert config.log_level == "DEBUG"
    assert config.schedule.mode == "cron"
    assert config.llm.provider == "deepseek"
    assert config.llm.api_key == "sk-from-env"
    assert [source.name for source in config.sources] == ["seed", "gateway"]
    assert config.data_dir == tmp_path / "out/data"


def test_load_json_config(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schedule": {"mode": "interval", "interval_minutes": 30}}), encoding="utf-8")
    config = load_config(path)
    assert config.schedule.interval_minutes == 30


def test_environment_variables_override_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JOBSINSIGHT_SCHEDULE_MODE", "daily")
    monkeypatch.setenv("JOBSINSIGHT_SCHEDULE_DAILY_TIMES", "06:00,18:00")
    monkeypatch.setenv("JOBSINSIGHT_LLM_MODEL", "gpt-from-env")
    monkeypatch.setenv("JOBSINSIGHT_SERVER_PORT", "9001")

    config = load_config(write_config(tmp_path))

    assert config.schedule.mode == "daily"
    assert config.schedule.daily_times == ["06:00", "18:00"]
    assert config.llm.model == "gpt-from-env"
    assert config.server.port == 9001


def test_empty_environment_variables_do_not_erase_file_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unset Actions Variables arrive as empty strings, not absent variables."""

    monkeypatch.setenv("JOBSINSIGHT_LLM_PROVIDER", "")
    monkeypatch.setenv("JOBSINSIGHT_LLM_MODEL", "   ")
    monkeypatch.setenv("JOBSINSIGHT_SCHEDULE_MODE", "")

    config = load_config(write_config(tmp_path))

    assert config.llm.provider == "deepseek"
    assert config.llm.model == "deepseek-chat"
    assert config.schedule.mode == "cron"


def test_missing_env_placeholder_becomes_empty_with_a_default(tmp_path: Path):
    config = load_config(write_config(tmp_path, '[llm]\napi_key = "${NOT_SET_ANYWHERE:-fallback}"\n'))
    assert config.llm.api_key == "fallback"


def test_runtime_overrides_are_layered_on_top(tmp_path: Path):
    path = write_config(tmp_path)
    config = load_config(path)
    save_overrides(config, {"schedule": {"mode": "daily", "daily_times": ["09:00"]}})

    reloaded = load_config(path)
    assert reloaded.schedule.mode == "daily"
    assert reloaded.schedule.daily_times == ["09:00"]


def test_unknown_option_is_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="unknown option"):
        load_config(write_config(tmp_path, "[schedule]\nnope = 1\n"))


def test_missing_explicit_config_file_is_an_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")


def test_redaction_hides_secrets():
    config = Config(llm=LLMSettings(api_key="sk-secret"))
    config.server.auth_token = "tok"
    config.sources = [
        SourceSettings(name="51job", headers={"Cookie": "do-not-print", "Referer": "https://we.51job.com/"})
    ]
    redacted = config.as_dict()
    rendered = json.dumps(redacted)
    assert redacted["llm"]["api_key"] == "***"
    assert redacted["server"]["auth_token"] == "***"
    assert redacted["sources"][0]["headers"] == {"Cookie": "***", "Referer": "***"}
    assert "do-not-print" not in rendered
    assert config.as_dict(redact=False)["llm"]["api_key"] == "sk-secret"


def test_shipped_config_enables_51job_without_committing_a_cookie():
    root = Path(__file__).resolve().parents[2]
    config_path = root / "automation" / "config.toml"
    workflow = (root / ".github" / "workflows" / "update-data.yml").read_text(encoding="utf-8")
    raw = config_path.read_text(encoding="utf-8")

    assert 'Cookie = "${JOB51_COOKIE}"' in raw
    assert "acw_" not in raw
    assert '\nname = "boss"' not in raw
    assert '\nname = "liepin-html"' not in raw
    assert "JOB51_COOKIE: ${{ secrets.JOB51_COOKIE }}" in workflow

    config = load_config(config_path)
    source = next(item for item in config.sources if item.name == "51job")
    enabled = {item.name for item in config.enabled_sources}

    assert source.enabled is True
    assert source.required is False
    assert source.type == "json_api"
    assert source.platform == "51job"
    assert source.keywords == ["医疗 AI", "医疗大模型", "医学影像 算法", "AI 制药", "药物研发 算法"]
    assert source.options["items_path"] == "resultbody.job.items"
    assert source.options["pages"] == 2
    assert source.options["delay_seconds"] == 1.5
    assert source.options["field_map"]["company"] == "fullCompanyName"
    assert source.options["field_map"]["salary_text"] == "provideSalaryString"
    assert source.options["field_map"]["description"] == "jobTags"
    assert "{keyword}" in source.urls[0] and "{page}" in source.urls[0] and "{timestamp}" in source.urls[0]
    assert "sign=" not in source.urls[0]
    assert "51job" in enabled
    assert "boss" not in enabled
    assert "liepin-html" not in enabled


@pytest.mark.parametrize(
    "settings",
    [
        ScheduleSettings(mode="nope"),
        ScheduleSettings(mode="daily", daily_times=[]),
        ScheduleSettings(mode="daily", daily_times=["99:00"]),
        ScheduleSettings(mode="cron", cron="not a cron"),
        ScheduleSettings(mode="interval", interval_minutes=0),
        ScheduleSettings(timezone="Mars/Olympus"),
    ],
)
def test_invalid_schedules_are_rejected(settings: ScheduleSettings):
    with pytest.raises(ConfigError):
        settings.validate()


def test_schedule_descriptions_and_cron_equivalents():
    daily = ScheduleSettings(mode="daily", daily_times=["00:00", "12:00"])
    assert daily.as_cron() == "0 0,12 * * *"
    assert "每天" in daily.describe()

    interval = ScheduleSettings(mode="interval", interval_minutes=120)
    assert interval.as_cron() == "0 */2 * * *"
    assert ScheduleSettings(mode="interval", interval_minutes=30).as_cron() == "*/30 * * * *"


def test_shipped_config_uses_deepseek_flash(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "JOBSINSIGHT_LLM_BASE_URL",
        "JOBSINSIGHT_LLM_API_KEY",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    # Unset Actions variables arrive as empty strings and must not replace the file.
    monkeypatch.setenv("JOBSINSIGHT_LLM_PROVIDER", "")
    monkeypatch.setenv("JOBSINSIGHT_LLM_MODEL", "  ")

    root = Path(__file__).resolve().parents[1]
    text = (root / "config.toml").read_text(encoding="utf-8")
    config = load_config(root / "config.toml", apply_overrides=False)

    assert 'api_key = "${JOBSINSIGHT_LLM_API_KEY:-}"' in text
    assert config.llm.provider == "deepseek"
    assert config.llm.model == "deepseek-flash"
    assert config.llm.base_url == "https://api.deepseek.com/v1"
    assert config.llm.api_key == ""
    assert config.llm.requires_api_key()


def test_api_key_falls_back_to_well_known_env_vars(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JOBSINSIGHT_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert LLMSettings().resolve_api_key() == "sk-openai"

    monkeypatch.setenv("MY_CUSTOM_KEY", "sk-custom")
    assert LLMSettings(api_key_env="MY_CUSTOM_KEY").resolve_api_key() == "sk-custom"


def test_duplicate_source_names_are_rejected(tmp_path: Path):
    text = '[[sources]]\nname = "dup"\ntype = "fixture"\n\n[[sources]]\nname = "dup"\ntype = "fixture"\n'
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(write_config(tmp_path, text))


def test_invalid_source_minimum_and_quality_gate_are_rejected():
    with pytest.raises(ConfigError, match="min_collected"):
        Config(sources=[SourceSettings(name="bad", min_collected=-1)]).validate()
    with pytest.raises(ConfigError, match="min_quality_score"):
        Config(output=OutputSettings(min_quality_score=101)).validate()


def test_local_config_file_is_preferred_over_shared_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JOBSINSIGHT_CONFIG", raising=False)
    write_config(tmp_path, '[llm]\nmodel = "from-shared"\n')
    write_config(tmp_path, '[llm]\nmodel = "from-local"\n', "config.local.toml")

    config = load_config(project_root=tmp_path)

    assert config.config_path is not None
    assert config.config_path.name == "config.local.toml"
    assert config.llm.model == "from-local"


def test_example_local_config_name_is_not_autoloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JOBSINSIGHT_CONFIG", raising=False)
    write_config(tmp_path, '[llm]\nmodel = "from-shared"\n')
    (tmp_path / "config.local.example.toml").write_text('[llm]\nmodel = "from-example"\n', encoding="utf-8")

    config = load_config(project_root=tmp_path)

    assert config.llm.model == "from-shared"


def test_explicit_config_path_beats_local_file_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    shared = write_config(tmp_path, '[llm]\nmodel = "shared"\n')
    write_config(tmp_path, '[llm]\nmodel = "local"\n', "config.local.toml")
    monkeypatch.setenv("JOBSINSIGHT_CONFIG", str(tmp_path / "config.local.toml"))

    config = load_config(shared)

    assert config.llm.model == "shared"


def test_jobsinsight_config_env_overrides_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_config(tmp_path, '[llm]\nmodel = "shared"\n')
    custom = tmp_path / "custom.toml"
    custom.write_text('[llm]\nmodel = "custom"\n', encoding="utf-8")
    monkeypatch.setenv("JOBSINSIGHT_CONFIG", str(custom))

    config = load_config(project_root=tmp_path)

    assert config.llm.model == "custom"
    assert config.config_path == custom


def test_blank_jobsinsight_config_env_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_config(tmp_path, '[llm]\nmodel = "shared"\n')
    monkeypatch.setenv("JOBSINSIGHT_CONFIG", "   ")

    config = load_config(project_root=tmp_path)

    assert config.llm.model == "shared"


def test_local_example_enables_browser_sources_and_ci_config_does_not(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "JOBSINSIGHT_CONFIG",
        "JOBSINSIGHT_LLM_PROVIDER",
        "JOBSINSIGHT_LLM_MODEL",
        "JOBSINSIGHT_LLM_BASE_URL",
        "JOBSINSIGHT_LLM_API_KEY",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    root = Path(__file__).resolve().parents[1]
    repo = root.parent
    ci = load_config(root / "config.toml", apply_overrides=False)
    local = load_config(root / "config.local.example.toml", apply_overrides=False)
    gitignore = (repo / ".gitignore").read_text(encoding="utf-8")

    assert all(source.type != "browser" or not source.enabled for source in ci.sources)
    assert not any(source.type == "browser" and source.enabled for source in ci.enabled_sources)
    browsers = [source for source in local.enabled_sources if source.type == "browser"]
    assert [source.name for source in browsers] == ["boss", "liepin", "job51"]
    assert all(source.required is False for source in browsers)
    assert all(source.options.get("pages") == 2 for source in browsers)
    assert all(float(source.options.get("delay_seconds", 0)) >= 1 for source in browsers)
    assert all("{keyword}" in url and "{page}" in url for source in browsers for url in source.urls)
    assert next(source for source in browsers if source.name == "liepin").options["page_start"] == 0
    assert {source.name for source in local.enabled_sources} >= {"seed", "job-discovery", "company-careers"}
    assert all(source.name != "51job" or source.type != "json_api" for source in local.sources)
    assert local.llm.provider == ci.llm.provider == "deepseek"
    assert local.llm.model == ci.llm.model == "deepseek-flash"
    assert "automation/config.local.toml" in gitignore
