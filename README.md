# A 1970s Jukebox, Reborn for AirPlay

My step-father bought a 1970s-era jukebox that, from what we can tell,
spent a number of years in service at a Waffle House. We cleaned it up and
gutted its electromechanical guts, original lighting, and speakers,
replacing them with an early-90s Sony receiver, 6x9 car speakers, a powered
subwoofer, and a Raspberry Pi running the fantastic
[shairport-sync](https://github.com/mikebrady/shairport-sync). The jukebox
is now an AirPlay speaker, reachable from any iPhone or Mac on the network.

It looked and sounded great — but the two 7-segment displays and the
12-button keypad were just sitting there dark, begging to be used again.
This repo is what's driving them: the same Pi now also runs the original
control panel, turning it into a "now playing" display and remote control
for a Mac running Music.app.

Play something over AirPlay from another room, and the panel picks it up
automatically: a rolling "songs played" counter ticks up on the original
3-digit display, and the jukebox's own numeric keypad lets you punch in a
3-digit code to queue a specific track from a shared playlist — the way the
machine worked when it actually took quarters. Two 14-segment alphanumeric
displays were added alongside the original panel to show artist, title, and
album as they scroll by, since the jukebox never had anything capable of
showing that on its own.

## How it fits together

```
 Mac (Music.app) ──AirPlay──▶ shairport-sync ──MQTT──▶ Raspberry Pi ──▶ panel hardware
       ▲                                                    │
       └──────────────── SSH / JavaScript for Automation ◀──┘
```

- **shairport-sync** receives the AirPlay stream and publishes track
  metadata and play/pause/stop events over MQTT.
- The Pi subscribes, drives the physical panel in real time, and turns
  keypad presses into playback commands — sent back to the Mac either over
  MQTT or directly via JavaScript for Automation over SSH, whichever proves
  more reliable at the time.
- A custom PCB and level shifter bridge the panel's original 5V shift-register
  and keypad-matrix electronics to the Pi's 3.3V GPIO, backed by a small
  Linux kernel driver that exposes the panel as a character device.

## What's in here

| Path | What it is |
|---|---|
| [`src/`](src) | The Python application: MQTT/AirPlay integration, keypad state machine, animated display rendering, playlist lookup |
| [`linux/jukeboxPanelModule/`](linux/jukeboxPanelModule) | Kernel driver exposing the panel over `/dev/jukebox_panel` (text) and `/dev/jukebox_panel_bin` (binary, segment-level) protocols |
| [`hardware/`](hardware) | KiCad schematics/PCB layouts for the panel driver board and level-shifter |
| [`systemd/`](systemd) | Boot-time services: autostart, and a config-fetch step that pulls settings from the Mac |
| [`docs/`](docs) | Wiring diagrams, deployment notes, and a from-scratch [functional specification](docs/SPECIFICATION.md) of the whole system's behavior |

## Notable bits

- **Runs on a read-only root filesystem.** The Pi is sandboxed with systemd
  (`ProtectSystem=strict`), so config changes happen by editing a file on the
  Mac, which the Pi fetches at boot — see [`docs/deployment.md`](docs/deployment.md).
- **Segment-by-segment reveal animations**, not just instant text writes —
  characters materialize one LED segment at a time on both the alphanumeric
  and 7-segment displays.
- **A real hardware protocol**, reverse-engineered and reimplemented: the
  panel's MM5450/MM5451 shift-register displays and matrix keypad are driven
  over a shared clock/data bus with no separate keypad wiring — see
  [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) for the full wire-level
  writeup.
- **Graceful degradation everywhere**: a lost MQTT connection, a Mac that's
  unreachable at boot, or a corrupt config file each fall back to a safe,
  visible state instead of crashing.

## Credit where it's due

None of this works without [shairport-sync](https://github.com/mikebrady/shairport-sync),
Mike Brady's open-source AirPlay audio receiver. It's what turns the Pi into
an AirPlay speaker in the first place, and its built-in MQTT metadata
publisher — track info and play/pause/stop events over MQTT — is the
signal this entire panel is built to react to. Everything in this repo is
downstream of that project.
