// AirPlay-recovery script for the macOS "Music" app, run as JavaScript for
// Automation (JXA) over SSH by MusicAppSSHWorker.recover_airplay_playback().
//
// MusicAppSSHWorker reads this file and substitutes the two placeholders
// below (each JSON-quoted, so they become valid JS string literals):
//   - airplay_device_name: the AirPlay device to select. Defaults to the
//     Raspberry Pi's own hostname, since that's what shairport-sync
//     advertises itself as over AirPlay unless configured otherwise --
//     it's NOT related to the playlist name.
//   - playlist_name: the Music.app playlist to start when nothing is
//     already playing. An independent, separately-configured value --
//     don't assume it matches airplay_device_name.
// The result is base64-encoded and piped into `osascript -l JavaScript`
// over the SSH connection -- so this file itself never needs to be
// deployed to the remote machine; only the SSH link does.
//
// Triggered as a last resort when ShairportSyncMQTTSource reports that
// shairport-sync's own MQTT remote-control path (playpause/nextitem/
// previtem/queue_next) has gone unacknowledged -- usually a sign the
// AirPlay session/device selection on the Music app side has dropped,
// which is what this script re-establishes: re-select the AirPlay device
// and resume/start playback from the playlist.
//
// Left as a plain top-level IIFE (no `function run(argv)`) since it's piped
// into osascript's stdin rather than invoked with arguments -- both names
// are baked into the script text before it's ever sent.
(() => {
  const Music = Application("Music");
  const deviceName = "__AIRPLAY_DEVICE_NAME__";
  const playlistName = "__PLAYLIST_NAME__";

  let device = null;
  let attempts = 10;
  while (device === null && attempts > 0) {
    attempts--;
    try {
      const candidate = Music.airplayDevices.byName(deviceName);
      candidate.available(); // force evaluation -- byName() alone doesn't throw for a missing device in JXA
      device = candidate;
    } catch (e) {
      delay(2);
    }
  }

  if (device === null) {
    return "Unable to find " + deviceName + " Airplay device";
  }

  if (!device.available()) {
    device.selected = false;
    return deviceName + " airplay selected, but not available";
  }

  // Always force a deselect/reselect cycle rather than only selecting when
  // device.selected() is false -- confirmed live (jukebox0, 2026-07-30)
  // that Music.app can get stuck reporting selected=true (and playerState
  // "playing") while the actual RTSP/AirPlay session has silently died --
  // e.g. the Pi rebooted mid-session -- with nothing in Music.app's own
  // scripting surface distinguishing that from a genuinely live
  // connection. This script only ever runs as a last resort already
  // (triggered because the MQTT remote-control path went unacknowledged),
  // so the brief interruption from an unconditional toggle is an
  // acceptable cost for actually fixing a stuck session instead of
  // silently no-op'ing on state that only *looks* fine.
  device.selected = false;
  delay(1);
  device.selected = true;
  device.soundVolume = 60;

  if (Music.playerState() === "paused") {
    Music.play();
  } else if (Music.playerState() !== "playing") {
    const playlist = Music.playlists.byName(playlistName);
    Music.play(playlist);
    Music.shuffleEnabled = true;
  }

  return "OK";
})();
