# Deployment: autostart, service management, read-only root

## How the app starts

`systemd/jukebox.service` (installed as `/etc/systemd/system/jukebox.service`)
runs the app on boot as the `simonbs` user, from the same checkout used for
development (`/home/simonbs/jukebox5`) — no separate deploy copy, no
dedicated service account. Isolation comes from systemd sandboxing instead
of a separate Unix user:

- `ProtectSystem=strict` + `ProtectHome=read-only` make the entire
  filesystem read-only *to this process*, independent of whether the
  underlying disk is actually mounted read-only (see below) — this was
  verified live (SSH key reads, hardware device access, MQTT all worked
  fine under it) rather than just assumed.
- `RuntimeDirectory=jukebox` gives it one small tmpfs-backed writable
  directory (`/run/jukebox`) it doesn't currently need — the app makes no
  runtime filesystem writes today — but is reserved for future use.
- `Restart=on-failure` / `RestartSec=5s` auto-restarts on a crash (verified
  with `SIGKILL` against the running process — a plain `SIGTERM` does
  *not* trigger a restart, by systemd design: that's its own "please stop"
  signal, excluded from `on-failure`'s restart triggers, same as
  `systemctl stop` would produce).

System-wide, `/etc/systemd/journald.conf` has `Storage=volatile` — the
journal lives in a RAM-backed ring buffer (`/run/log/journal`) rather than
on disk, so logs never contribute to SD card wear either, whether or not
the root filesystem itself is read-only.

## Managing the service

```sh
systemctl status jukebox          # is it running, since when, current PID
journalctl -u jukebox -f          # live log tail (Ctrl-C to stop watching)
journalctl -u jukebox -n 100      # last 100 lines
sudo systemctl restart jukebox    # e.g. after editing config.ini or pulling new code
sudo systemctl stop jukebox       # stop without disabling autostart
sudo systemctl disable jukebox    # stop autostarting on boot
```

Because `Storage=volatile`, `journalctl -u jukebox` only shows logs since
the last boot (or since `systemd-journald` was last restarted) — there's no
persistent history across reboots, by design.

## Switching between read-only and read-write

The root filesystem is **not yet** read-only on this device — the steps
above (sandboxing, volatile journal) were deliberately chosen so the app
already behaves correctly either way, but the actual switch hasn't been
flipped. When you're ready, Raspberry Pi OS's built-in overlay-root
mechanism is the way to do it (confirmed against this device's
`raspi-config`, not just recalled from memory):

```sh
# check current state (no reboot, safe to run any time)
raspi-config nonint get_overlay_now    # 0 = currently running read-only, 1 = currently read-write
raspi-config nonint get_overlay_conf   # 0 = configured to be read-only on next boot, 1 = not

# switch to read-only (protects the SD card; the whole point of this setup)
sudo raspi-config nonint enable_overlayfs
sudo reboot

# switch back to read-write (for maintenance -- editing config.ini, git pull, etc.)
sudo raspi-config nonint disable_overlayfs
sudo reboot
```

Both directions require a reboot to take effect — there's no live-remount
option. **The first time you enable it**, `enable_overlayfs` will
`apt-get install overlayroot` if it isn't already present (it isn't, as of
this writing), so make sure the device has internet access at that moment.

Once overlay-root is active, any writes anywhere on the root filesystem
(including, harmlessly, Python's own `.pyc` bytecode cache, which the
service already sets `PYTHONDONTWRITEBYTECODE=1` to avoid attempting
anyway) land in a RAM-backed delta and are discarded on reboot rather than
failing outright — so switching it on doesn't require re-verifying
anything about the app; nothing changes for it either way.
