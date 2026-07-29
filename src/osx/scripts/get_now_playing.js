// Read-only companion to recover_airplay_playback.js, run as JavaScript
// for Automation (JXA) over SSH by MusicAppSSHWorker.get_now_playing().
//
// Covers a gap shairport-sync's own MQTT metadata can't: it only publishes
// artist/title/album/track_id once, at the moment a track starts, with no
// retained message a late subscriber can catch up on. If the Mac was
// already mid-track when this jukebox process (re)started, its fresh MQTT
// subscription sees nothing until the *next* track change, leaving the
// display blank in the meantime even though playback itself never
// stopped. This script lets main.py ask the Mac directly instead, once,
// at startup.
//
// Also reports whether this Pi's own AirPlay device (airplaySelected) is
// actually the one selected and available -- Music.app reporting
// playerState "playing" is NOT enough on its own to conclude nothing needs
// recovering: it could be playing to a completely different output (its
// own speakers, another AirPlay device) while this jukebox has no session
// at all. Confirmed as a real gap during the Pi Zero port bring-up:
// startup skipped AirPlay-device recovery just because *something* was
// playing on the Mac, even though it was never actually being AirPlayed to
// this device.
//
// MusicAppSSHWorker reads this file and substitutes airplay_device_name
// (JSON-quoted, matching recover_airplay_playback.js's convention) --
// unrelated to which track is playing, just which AirPlay device to check.
//
// Returns JSON on stdout: {"playerState": ..., "airplaySelected": bool}
// alone if nothing is loaded, or with "name"/"artist"/"album"/
// "persistentID" added if a track is (Music.currentTrack throws when
// there's no current track, same as recover_airplay_playback.js's
// airplayDevices.byName() does for a missing device).
(() => {
  const Music = Application("Music");
  const deviceName = "__AIRPLAY_DEVICE_NAME__";
  const playerState = Music.playerState();

  let airplaySelected = false;
  try {
    const device = Music.airplayDevices.byName(deviceName);
    airplaySelected = device.available() && device.selected(); // force evaluation -- see comment above
  } catch (e) {
    airplaySelected = false;
  }

  let track;
  try {
    track = Music.currentTrack();
    track.name(); // force evaluation -- see recover_airplay_playback.js's comment
  } catch (e) {
    return JSON.stringify({ playerState: playerState, airplaySelected: airplaySelected });
  }

  return JSON.stringify({
    playerState: playerState,
    airplaySelected: airplaySelected,
    name: track.name(),
    artist: track.artist(),
    album: track.album(),
    persistentID: track.persistentID(),
  });
})();
