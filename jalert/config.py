"""Configuration loading with defaults and path resolution.

Three layers are merged in order, each overriding the previous one:

1. :data:`DEFAULTS` — hard-coded sane defaults.
2. ``config.json`` — the shareable, committed configuration (journals, keywords,
   thresholds). **Never put a push key here.**
3. ``config.local.json`` — optional, sitting next to ``config.json``, git-ignored.
   This is where push keys belong on a personal machine.

Environment variables are applied last so CI (GitHub Actions) can inject secrets
without any file on disk. See :data:`SECRET_ENV`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Deep-merged on top of ``config.json`` when present. Git-ignored: this is the
#: file that holds per-machine secrets.
LOCAL_OVERLAY_NAME = "config.local.json"

#: ``环境变量 -> (渠道, 字段)``。变量非空时覆盖配置文件里的值，并把该渠道打开。
#: 用于 GitHub Actions：密钥存在仓库 Secrets 里，不进任何文件。
SECRET_ENV: dict[str, tuple[str, str]] = {
    "JALERT_SERVERCHAN_SENDKEY": ("serverchan", "sendkey"),
    "JALERT_PUSHPLUS_TOKEN": ("pushplus", "token"),
    "JALERT_BARK_KEY": ("bark", "key"),
}

#: 同上，但这些字段只覆盖、不隐式启用渠道（是渠道的附属参数）。
OPTIONAL_ENV: dict[str, tuple[str, str]] = {
    "JALERT_BARK_SERVER": ("bark", "server"),
}

DEFAULTS: dict = {
    "project": {"name": "Journal Alert", "timezone": "Asia/Shanghai"},
    "window": {
        "days": 3,
        "max_catchup_days": 30,
        "max_items_per_journal": 60,
        "workers": 6,
        "rss_timeout_seconds": 25,
        "api_timeout_seconds": 45,
        "retries": 2,
        "sources": {"rss": True, "openalex": True, "crossref": True},
    },
    "output": {
        "dir": "reports",
        "keep_days": 365,
        "max_entries": 0,
        "open_after_run": False,
        "write_json_snapshot": True,
        # "full"  = the whole per-source table (best for debugging a broken feed)
        # "summary" = one line when healthy, a short table only for failures
        # "none"  = never mention data sources in the report
        "source_status": "full",
        # YAML front matter on top of each report, so Obsidian properties and
        # Dataview can query it. Skip it if you only ever read the raw Markdown.
        "frontmatter": True,
        # Static card-wall page rebuilt from every report in ``dir`` after each
        # run. Purely additive: if it fails, the run still succeeds.
        "cards": True,
        "cards_html": "docs/index.html",
    },
    "keywords": [],
    "exclude_terms": [],
    "exclude_doi_prefixes": [],
    "tiers": {"must_read": 12, "worth_reading": 6, "min_score": 3},
    "journals": [],
    "push": {
        "enabled": False,
        "skip_when_empty": True,
        "max_items": 6,
        "max_chars": 1800,
        "channels": {
            "serverchan": {"enabled": False, "sendkey": ""},
            "pushplus": {"enabled": False, "token": ""},
            "bark": {"enabled": False, "key": "", "server": "https://api.day.app", "sound": "bird"},
        },
    },
    "log": {"dir": "logs", "level": "INFO"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge dicts; lists and scalars from ``override`` replace."""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict:
    config_path = Path(
        path or os.environ.get("JALERT_CONFIG") or (PROJECT_ROOT / "config.json")
    )
    if not config_path.is_file():
        raise FileNotFoundError(f"config not found: {config_path}")
    cfg = _deep_merge(DEFAULTS, json.loads(config_path.read_text(encoding="utf-8")))

    overlay_path = Path(
        os.environ.get("JALERT_CONFIG_LOCAL") or config_path.with_name(LOCAL_OVERLAY_NAME)
    )
    if overlay_path.is_file():
        cfg = _deep_merge(cfg, json.loads(overlay_path.read_text(encoding="utf-8")))

    _apply_env_overrides(cfg)

    cfg["_root"] = str(PROJECT_ROOT)
    cfg["_config_path"] = str(config_path)
    cfg["_local_overlay"] = str(overlay_path) if overlay_path.is_file() else ""
    cfg["reports_dir"] = str(_resolve(cfg["output"]["dir"]))
    cfg["log_dir"] = str(_resolve(cfg["log"]["dir"]))
    cfg["state_db"] = str(_resolve("state") / "seen.sqlite")
    return cfg


def _apply_env_overrides(cfg: dict) -> None:
    """Let environment variables win, so CI needs no secrets on disk."""
    channels = cfg.setdefault("push", {}).setdefault("channels", {})
    filled = False
    for env_name, (channel, field) in SECRET_ENV.items():
        value = os.environ.get(env_name, "").strip()
        if not value:
            continue
        node = channels.setdefault(channel, {})
        node[field] = value
        node["enabled"] = True  # a key present means "use this channel"
        filled = True
    for env_name, (channel, field) in OPTIONAL_ENV.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            channels.setdefault(channel, {})[field] = value

    if filled:
        cfg["push"]["enabled"] = True
    flag = os.environ.get("JALERT_PUSH_ENABLED", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        cfg["push"]["enabled"] = False
    elif flag in ("1", "true", "yes", "on"):
        cfg["push"]["enabled"] = True


def describe_secret_sources(cfg: dict) -> list[str]:
    """Human-readable list of which channels are armed and where the key came from."""
    channels = cfg.get("push", {}).get("channels", {})
    out: list[str] = []
    for channel, field, label in (
        ("serverchan", "sendkey", "Server酱"),
        ("pushplus", "token", "PushPlus"),
        ("bark", "key", "Bark"),
    ):
        env_name = next((k for k, v in SECRET_ENV.items() if v == (channel, field)), "")
        if env_name and os.environ.get(env_name, "").strip():
            out.append(f"{label}（环境变量 {env_name}）")
        elif channels.get(channel, {}).get("enabled") and channels[channel].get(field):
            out.append(f"{label}（配置文件）")
    return out



def _resolve(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def enabled_journals(cfg: dict) -> list[dict]:
    return [j for j in cfg.get("journals", []) if j.get("enabled", True)]
