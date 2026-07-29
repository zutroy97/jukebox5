// Immediate track playback for the macOS "Music" app, run as JavaScript
// for Automation (JXA) over SSH by MusicAppSSHWorker.play_track().
//
// Used for keypad codes in the "immediate play" range (see §7 of
// docs/SPECIFICATION.md): interrupts whatever's currently playing and
// starts this track right away. Replaces shairport-sync's MQTT/DACP
// queue_next()+send_remote_command("nextitem") combination for this case
// -- see playpause.js for why. The *other* track-selection range ("queued
// behind the current track, don't interrupt") still goes through DACP's
// queue_next, since that's a genuine AirPlay-remote queue operation with
// no equivalent exposed in Music.app's scripting dictionary -- the "Up
// Next" queue has never been scriptable via AppleScript/JXA.
//
// MusicAppSSHWorker reads this file and substitutes both placeholders
// below (each JSON-quoted, so they become valid JS string literals):
//   - playlist_name: the same Music.app playlist used elsewhere
//     (recover_airplay_playback.js, get_playlist_tracks.js).
//   - persistent_id: the target track's persistent ID, as returned by
//     get_playlist_tracks.js/get_now_playing.js and matched against
//     Playlist's lookup by persistent ID.
//
// Track lookup loops over playlist.tracks rather than using JXA's
// `whose()` filter, matching get_playlist_tracks.js's style.
(() => {
  const Music = Application("Music");
  const playlistName = "__PLAYLIST_NAME__";
  const persistentId = "__PERSISTENT_ID__";

  const playlist = Music.playlists[playlistName];
  const tracks = playlist.tracks;

  let target = null;
  for (let i = 0; i < tracks.length; i++) {
    if (tracks[i].persistentID() === persistentId) {
      target = tracks[i];
      break;
    }
  }

  if (target === null) {
    return "Unable to find track with persistentID " + persistentId + " in playlist " + playlistName;
  }

  try {
    Music.play(target);
  } catch (e) {
    return "play failed: " + e;
  }
  return "OK";
})();
