"""全局配置：环境变量（.env）+ config/app.yaml + 路径。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _load_dotenv(path: Path) -> None:
    """极简 .env 读取：只填充尚未设置的环境变量，不依赖 python-dotenv。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


class Settings:
    """运行时设置。每次访问都读环境变量，便于测试里用 monkeypatch 覆盖。"""

    @property
    def llm_mode(self) -> str:
        return os.environ.get("LLM_MODE", "demo").strip().lower() or "demo"

    @property
    def llm_base_url(self) -> str:
        return os.environ.get("LLM_BASE_URL", "").strip()

    @property
    def llm_model(self) -> str:
        return os.environ.get("LLM_MODEL", "").strip()

    @property
    def llm_api_key(self) -> str:
        return os.environ.get("LLM_API_KEY", "").strip()

    @property
    def method_endpoint(self) -> str:
        return os.environ.get("METHOD_ENDPOINT", "").strip().rstrip("/")

    @property
    def risk_endpoint(self) -> str:
        return os.environ.get("RISK_ENDPOINT", "").strip().rstrip("/")

    @property
    def solver_mode(self) -> str:
        m = os.environ.get("SOLVER_MODE", "builtin").strip().lower() or "builtin"
        return m if m in ("builtin", "mock", "import", "external") else "builtin"

    @property
    def solver_cmd(self) -> str:
        return os.environ.get("SOLVER_CMD", "").strip()

    @property
    def snapshot_dir(self) -> Path:
        p = Path(os.environ.get("SNAPSHOT_DIR", "./data/snapshots"))
        return p if p.is_absolute() else (ROOT / p).resolve()

    @property
    def runs_dir(self) -> Path:
        p = os.environ.get("RUNS_DIR")
        return Path(p) if p else RUNS_DIR

    @property
    def db_path(self) -> Path:
        p = os.environ.get("WORKBENCH_DB")
        return Path(p) if p else self.runs_dir / "workbench.sqlite"


settings = Settings()


@lru_cache(maxsize=1)
def app_config() -> dict[str, Any]:
    with open(CONFIG_DIR / "app.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def knowledge() -> dict[str, Any]:
    with open(CONFIG_DIR / "knowledge.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def operators_config() -> dict[str, Any]:
    with open(CONFIG_DIR / "operators.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def reload_configs() -> None:
    app_config.cache_clear()
    knowledge.cache_clear()
    operators_config.cache_clear()
