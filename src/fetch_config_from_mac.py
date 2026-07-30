#!/usr/bin/env python3
"""Runs once at boot, before jukebox.service starts (see
systemd/jukebox-config-fetch.service, which runs this and orders itself
Before= that unit) -- fetches ~/.jukebox/config.ini from the machine
running the macOS "Music" app, if it's there, and overwrites this
checkout's config.ini with it. A person can edit config.ini on the Mac (a
normal always-writable desktop) instead of on this device directly.

Does no validation of the fetched content beyond "is it non-empty" --
config.py's validate_config() and main.py's own startup are responsible
for deciding whether config.ini is actually usable and falling back to
config.golden.ini if not, so that single source of truth for "is this
config usable" doesn't get duplicated here.

Never fails the boot: any error (Mac unreachable, no override file, a
connection problem) is logged and this exits 0 regardless, so
jukebox.service always starts on whatever config.ini was already there.

Deliberately a plain, non-hardware script (imports nothing from drivers/,
observers/, etc.) so it stays runnable as a lightweight, non-sandboxed
systemd oneshot ahead of the real (ProtectSystem=strict-sandboxed)
jukebox.service, which cannot write config.ini itself.
"""
import logging
import os
import sys

import paramiko

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import Config, GOLDEN_CONFIG_PATH, SSHWorkerConfig  # noqa: E402

_REMOTE_OVERRIDE_PATH = "~/.jukebox/config.ini"
_FETCH_TIMEOUT_S = 10.0
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")


def _load_ssh_config() -> "SSHWorkerConfig | None":
    """Reads [sshWorker], trying config.ini first and falling back to
    config.golden.ini if config.ini is missing/unparseable/has no
    [sshWorker] section -- so a previous fetch that left config.ini
    corrupted doesn't also strand this script without a way to reach the
    Mac and fetch a fix on the next boot."""
    for path in (_CONFIG_PATH, GOLDEN_CONFIG_PATH):
        try:
            ssh_config = Config(path).ssh_worker()
        except Exception as e:
            logging.warning("Could not read [sshWorker] from %s: %s", path, e)
            continue
        if ssh_config is not None:
            return ssh_config
    return None


def _fetch(ssh_config: SSHWorkerConfig) -> "str | None":
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
            logging.info("No config override present on the Mac at %s", _REMOTE_OVERRIDE_PATH)
            return None
        return stdout.read().decode("utf-8", errors="replace")
    except Exception as e:
        logging.warning("Could not fetch a config override from the Mac: %s", e)
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ssh_config = _load_ssh_config()
    if ssh_config is None:
        logging.info("No usable [sshWorker] config in config.ini or config.golden.ini; nothing to fetch")
        return

    remote_text = _fetch(ssh_config)
    if remote_text is None:
        return

    if not remote_text.strip():
        logging.warning("Config override on the Mac is empty; ignoring")
        return

    try:
        with open(_CONFIG_PATH, "r") as f:
            if f.read() == remote_text:
                logging.info("Config override matches config.ini already; nothing to do")
                return
    except OSError:
        pass  # config.ini missing/unreadable -- fetched text should still be written

    with open(_CONFIG_PATH, "w") as f:
        f.write(remote_text)
    logging.info("Copied a new config.ini from the Mac")


if __name__ == "__main__":
    main()
