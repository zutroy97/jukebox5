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

  if (!device.selected()) {
    device.selected = true;
    device.soundVolume = 60;
  }

  if (Music.playerState() === "paused") {
    Music.play();
  } else if (Music.playerState() !== "playing") {
    const playlist = Music.playlists.byName(playlistName);
    Music.play(playlist);
    Music.shuffleEnabled = true;
  }

  return "OK";
})();
