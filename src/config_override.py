import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

import paramiko

from config import Config, SSHWorkerConfig

# Where to look for an override config.ini on the machine running the Music
# app -- a plain text file a person can edit there instead of on jukebox0,
# which is read-only to the jukebox.service process under systemd
# (ProtectSystem=strict -- see _RUNTIME_DIR below) independent of whether
# jukebox0's own root filesystem happens to be read-only too.
_REMOTE_OVERRIDE_PATH = "~/.jukebox/config.ini"
_FETCH_TIMEOUT_S = 10.0

# systemd's jukebox.service unit runs with ProtectSystem=strict +
# ProtectHome=read-only, making the *entire* filesystem read-only to this
# process regardless of whether the underlying disk/overlay itself is
# writable -- confirmed the hard way (EROFS writing straight over
# config.ini, not just when jukebox0's own root-filesystem overlay
# happens to be read-only). RuntimeDirectory=jukebox in that same unit
# exists specifically to give the process one small writable tmpfs
# directory for exactly this kind of need. Falls back to a path next to
# config_path for manual/dev runs outside systemd, where nothing is
# sandboxed and /run/jukebox won't exist.
_RUNTIME_DIR = "/run/jukebox"
_OVERRIDE_CACHE_FILENAME = "config_override.ini"


def override_cache_path(config_path: str) -> str:
    if os.path.isdir(_RUNTIME_DIR):
        return os.path.join(_RUNTIME_DIR, _OVERRIDE_CACHE_FILENAME)
    return os.path.join(os.path.dirname(config_path), _OVERRIDE_CACHE_FILENAME)


def active_config_path(config_path: str) -> str:
    """The config.ini this process should actually load from: a
    previously-applied override cached in override_cache_path() if one
    exists (e.g. surviving an execv-based restart within the same systemd
    service instance -- see check_and_apply_override()), otherwise
    config_path itself."""
    cache_path = override_cache_path(config_path)
    return cache_path if os.path.exists(cache_path) else config_path

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
    """Checks _REMOTE_OVERRIDE_PATH on the Mac for a config different from
    the one this process actually started with (active_config_path(),
    which may itself already be a cached override from an earlier
    restart). If it's valid, caches it at override_cache_path() -- never
    config_path itself, which is read-only under the systemd service (see
    _RUNTIME_DIR above). Leaves everything untouched if the override is
    missing, unreachable, identical to what's already active, or
    invalid."""
    try:
        ssh_config = config.ssh_worker()
    except ValueError:
        return OverrideResult(applied=False)  # local config itself is broken; let normal startup surface that
    if ssh_config is None:
        return OverrideResult(applied=False)  # no [sshWorker] configured -- nothing to check against

    remote_text = _fetch_override_text(ssh_config)
    if remote_text is None:
        return OverrideResult(applied=False)

    with open(active_config_path(config_path), "r") as f:
        local_text = f.read()
    if remote_text == local_text:
        return OverrideResult(applied=False)  # already applied -- avoid restarting every boot

    error = _validate_override_text(remote_text)
    if error is not None:
        return OverrideResult(applied=False, error=error)

    cache_path = override_cache_path(config_path)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        f.write(remote_text)
    return OverrideResult(applied=True)
