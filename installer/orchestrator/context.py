"""Install context: the configurator's output, the paths this run uses, and
a mutable `state` dict for objects that live across phases (the archinstall
config handler and mirror list handler)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class InstallContext:
    config_path: Path
    creds_path: Path

    user_configuration: dict
    user_credentials: dict
    ashlaros_install: dict[str, Any]

    target: Path = Path("/mnt")
    state_dir: Path = Path("/run/ashlaros-install")
    log_path: Path = Path("/var/log/ashlaros-install.log")

    # Populated by phases, read by later ones: 'arch_config_handler',
    # 'mirror_handler', 'luks_partition'.
    state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> InstallContext:
        config_str = os.environ.get("ASHLAROS_INSTALL_CONFIG")
        creds_str = os.environ.get("ASHLAROS_INSTALL_CREDS")
        if not config_str or not creds_str:
            raise RuntimeError(
                "ASHLAROS_INSTALL_CONFIG and ASHLAROS_INSTALL_CREDS must both be set"
            )

        config_path = Path(config_str)
        creds_path = Path(creds_str)
        for path in (config_path, creds_path):
            if not path.is_file():
                raise RuntimeError(f"{path} does not exist")

        user_configuration = json.loads(config_path.read_text())
        user_credentials = json.loads(creds_path.read_text())

        ashlaros_install = user_configuration.get("ashlaros_install")
        if not ashlaros_install:
            raise RuntimeError("user_configuration.json carries no ashlaros_install block")

        return cls(
            config_path=config_path,
            creds_path=creds_path,
            user_configuration=user_configuration,
            user_credentials=user_credentials,
            ashlaros_install=ashlaros_install,
            target=Path(ashlaros_install.get("target_mount", "/mnt")),
        )

    @property
    def username(self) -> str:
        users = self.user_credentials.get("users") or []
        if users and users[0].get("username"):
            return users[0]["username"]
        raise RuntimeError("user_credentials.json contains no users")

    @property
    def encrypt(self) -> bool:
        return bool(self.ashlaros_install.get("encrypt"))

    @property
    def autologin(self) -> bool:
        return bool(self.ashlaros_install.get("autologin"))

    @property
    def esp_mount(self) -> str:
        return self.ashlaros_install.get("boot", {}).get("esp_mount", "/boot")
