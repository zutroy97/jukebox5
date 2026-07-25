// AirPlay-recovery script for the macOS "Music" app, run as JavaScript for
// Automation (JXA) over SSH by MusicAppSSHWorker.recover_airplay_playback().
//
// MusicAppSSHWorker reads this file, substitutes the placeholder below with
// the configured airplay_device_name (JSON-quoted, so it becomes a valid JS
// string literal), base64-encodes the result, and pipes it into
// `osascript -l JavaScript` over the SSH connection -- so this file itself
// never needs to be deployed to the remote machine; only the SSH link does.
//
// Triggered as a last resort when ShairportSyncMQTTSource reports that
// shairport-sync's own MQTT remote-control path (playpause/nextitem/
// previtem/queue_next) has gone unacknowledged -- usually a sign the
// AirPlay session/device selection on the Music app side has dropped,
// which is what this script re-establishes: re-select the named AirPlay
// device and resume/start playback from the identically-named playlist.
//
// Left as a plain top-level IIFE (no `function run(argv)`) since it's piped
// into osascript's stdin rather than invoked with arguments -- the device
// name is baked into the script text before it's ever sent.
(() => {
  const Music = Application("Music");
  const deviceName = "__AIRPLAY_DEVICE_NAME__";

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

  if (!device.selected()) {
    device.selected = true;
    device.soundVolume = 60;
  }

  if (Music.playerState() === "paused") {
    Music.play();
  } else if (Music.playerState() !== "playing") {
    const playlist = Music.playlists.byName(deviceName);
    Music.play(playlist);
    Music.shuffleEnabled = true;
  }

  return "OK";
})();
