"""Where Crucible keeps what it fetches and writes, resolved once and always absolute (ADR-0068).

The product flow never depends on the working directory. Its home folder holds three things:

``data/``         datasets fetched by ``crucible backtest`` (one per symbols + window)
``experiments/``  every run's artifact folder and the trial registry
``cache/``        raw provider answers (a re-run of the same fetch is offline)

Resolution order: the ``home`` argument, the ``CRUCIBLE_HOME`` environment variable, the
``home`` entry of the settings file (``crucible config set-home PATH`` writes it, once), then the
platform default (``%LOCALAPPDATA%\\Crucible`` on Windows, ``$XDG_DATA_HOME/crucible`` or
``~/.local/share/crucible`` elsewhere). The settings file itself lives at a fixed per-user
location, so it can always be found.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from crucible.core.errors import ConfigurationError

HOME_ENV = "CRUCIBLE_HOME"


def settings_path() -> Path:
    """The per-user settings file (a small JSON object)."""
    override = os.environ.get("CRUCIBLE_SETTINGS")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "crucible" / "settings.json"


def _default_home() -> Path:
    windows = os.name == "nt"
    if windows:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Crucible"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "crucible"


def read_settings() -> dict[str, object]:
    path = settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        msg = f"the settings file {path} is unreadable ({exc}); fix or delete it"
        raise ConfigurationError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"the settings file {path} must hold a JSON object; fix or delete it"
        raise ConfigurationError(msg)
    return {str(k): v for k, v in raw.items()}


def set_home(path: str | Path) -> Path:
    """Remembers ``path`` as the home folder for every later run (creates it)."""
    home = Path(path).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    settings = read_settings()
    settings["home"] = str(home)
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return home


@dataclass(frozen=True, slots=True)
class Home:
    """The three folders of a Crucible home (all absolute)."""

    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def experiments(self) -> Path:
        return self.root / "experiments"

    @property
    def cache(self) -> Path:
        return self.root / "cache" / "providers"

    @property
    def scratch(self) -> Path:
        return self.root / "scratch"

    def ensure(self) -> Home:
        for folder in (self.data, self.experiments, self.cache, self.scratch):
            folder.mkdir(parents=True, exist_ok=True)
        return self


def resolve_home(home: str | Path | None = None) -> Home:
    """The home folder (created if missing). See the module docstring for the order."""
    if home is not None:
        root = Path(home).expanduser().resolve()
    elif os.environ.get(HOME_ENV):
        root = Path(os.environ[HOME_ENV]).expanduser().resolve()
    else:
        configured = read_settings().get("home")
        root = Path(str(configured)).resolve() if configured else _default_home().resolve()
    return Home(root).ensure()
