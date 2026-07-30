import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

import paramiko

from config import Config, SSHWorkerConfig

# Where to look for an override config.ini on the machine running the Music
# app -- a plain text file a person can edit there instead of on jukebox0
# (whose root filesystem may be mounted read-only -- see docs/deployment.md).
_REMOTE_OVERRIDE_PATH = "~/.jukebox/config.ini"
_FETCH_TIMEOUT_S = 10.0

_logger = logging.getLogger("ConfigOverride")


@dataclass(frozen=True)
class OverrideResult:
    # True if a new, valid config was found and written to config_path --
    # the caller should restart the process to pick it up cleanly rather
    # than trying to hot-swap already-constructed objects (MQTT client,
    # panel driver, etc.) to the new settings.
    applied: bool
    # Set only when an override was found but rejected -- the caller
    # should surface this (log/display) and continue on the existing,
    # unchanged local config.
    error: Optional[str] = None


def _fetch_override_text(ssh_config: SSHWorkerConfig) -> Optional[str]:
    """Connects to the Mac and returns the contents of
    _REMOTE_OVERRIDE_PATH there, or None if it doesn't exist or the Mac
    isn't reachable right now -- both treated as "nothing to override"
    rather than an error, since this check must never block startup on
    the Mac being up. A short-lived, one-off connection, deliberately
    separate from MusicAppSSHWorker's long-lived auto-reconnecting one,
    which isn't built for "connect, run one command, disconnect"."""
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy() if not ssh_config.strict_host_key_checking else paramiko.RejectPolicy()
    )
    try:
        client.connect(
            hostname=ssh_config.host,
            port=ssh_config.port,
            username=ssh_config.username,
            key_filename=ssh_config.key_path,
            timeout=ssh_config.connect_timeout_s,
            allow_agent=False,
            look_for_keys=False,
        )
        _, stdout, _stderr = client.exec_command(
            f"cat {_REMOTE_OVERRIDE_PATH}", timeout=_FETCH_TIMEOUT_S
        )
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            return None  # most commonly "no such file" -- no override present
        return stdout.read().decode("utf-8", errors="replace")
    except Exception as e:
        _logger.warning("Could not check for a config override on the Mac: %s", e)
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def _validate_override_text(text: str) -> Optional[str]:
    """Returns None if `text` is a usable config.ini -- it parses, and
    every Config accessor that validates its own section succeeds --
    or an error message describing what's wrong with it otherwise.
    Validates the same way Config already validates itself (each
    accessor raises on its own section rather than at construction), so
    there's no separate validation logic to keep in sync."""
    fd, temp_path = tempfile.mkstemp(suffix=".ini")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        candidate = Config(temp_path)
        candidate.panel()
        candidate.mqtt()
        candidate.ssh_worker()
        candidate.track_selection_feedback()
        candidate.playback_pause_flash()
        candidate.display_fields()
        candidate.shutdown_display()
        candidate.logging()
        # 8/12 match the two alphanumeric displays' actual widths (see
        # led0/led1 in main.py) -- the only widths animation_for_width()
        # is ever actually called with.
        candidate.animation_for_width(8)
        candidate.animation_for_width(12)
    except Exception as e:
        return str(e)
    finally:
        os.remove(temp_path)
    return None


def check_and_apply_override(config: Config, config_path: str) -> OverrideResult:
    """Checks _REMOTE_OVERRIDE_PATH on the Mac for a config.ini different
    from the one at config_path; if it's valid, writes it to config_path.
    Never touches config_path if the override is missing, unreachable,
    identical to what's already there, or invalid."""
    try:
        ssh_config = config.ssh_worker()
    except ValueError:
        return OverrideResult(applied=False)  # local config itself is broken; let normal startup surface that
    if ssh_config is None:
        return OverrideResult(applied=False)  # no [sshWorker] configured -- nothing to check against

    remote_text = _fetch_override_text(ssh_config)
    if remote_text is None:
        return OverrideResult(applied=False)

    with open(config_path, "r") as f:
        local_text = f.read()
    if remote_text == local_text:
        return OverrideResult(applied=False)  # already applied -- avoid restarting every boot

    error = _validate_override_text(remote_text)
    if error is not None:
        return OverrideResult(applied=False, error=error)

    with open(config_path, "w") as f:
        f.write(remote_text)
    return OverrideResult(applied=True)
