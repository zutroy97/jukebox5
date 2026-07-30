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

## SSH key setup: passwordless access to the Mac ([sshWorker])

`[sshWorker]` (see `src/config.ini`) needs to reach the Mac account running
the "Music" app over SSH with no password prompt -- password auth isn't
supported, only `key_path`. Steps to set this up on a new jukebox host:

```sh
# 1. On the jukebox host: generate a key pair if one doesn't already exist
#    for this purpose. Match the filename to whatever you'll put in
#    [sshWorker]'s key_path -- on jukebox0 this is ed25519 but kept under
#    the traditional id_rsa filename, since that's what key_path pointed
#    at when the key was generated; either naming works, they just have
#    to agree.
ssh-keygen -t ed25519 -f ~/.ssh/id_rsa -N ""

# 2. Copy the public key to the Mac's authorized_keys (prompts for the
#    Mac account's password once, this one time only)
ssh-copy-id -i ~/.ssh/id_rsa.pub simonbs@mbp2017

# 3. Verify it actually connects with no prompt at all
ssh -o BatchMode=yes simonbs@mbp2017 echo ok
```

Prerequisites on the Mac side: Remote Login must be on (System Settings →
General → Sharing → Remote Login), and the account has to be permitted
there. `~/.ssh` on the Mac should end up `700` and `authorized_keys`
`600` -- `ssh-copy-id` sets these correctly on its own; if setting it up
by hand instead, set them explicitly, since `sshd` silently refuses keys
under overly-permissive directory/file modes.

With `strict_host_key_checking=false` (the `[sshWorker]` default), the
Mac's host key is trusted and added to the jukebox host's
`~/.ssh/known_hosts` automatically on first connect -- no manual
`ssh-keyscan` step needed unless you've set that option to `true`.
