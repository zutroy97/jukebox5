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
// Returns JSON on stdout: {"playerState": "playing"|"paused"|"stopped"|...}
// alone if nothing is loaded, or with "name"/"artist"/"album"/
// "persistentID" added if a track is (Music.currentTrack throws when
// there's no current track, same as recover_airplay_playback.js's
// airplayDevices.byName() does for a missing device).
(() => {
  const Music = Application("Music");
  const playerState = Music.playerState();

  let track;
  try {
    track = Music.currentTrack();
    track.name(); // force evaluation -- see comment above
  } catch (e) {
    return JSON.stringify({ playerState: playerState });
  }

  return JSON.stringify({
    playerState: playerState,
    name: track.name(),
    artist: track.artist(),
    album: track.album(),
    persistentID: track.persistentID(),
  });
})();
