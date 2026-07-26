// Playlist-enumeration script for the macOS "Music" app, run as
// JavaScript for Automation (JXA) over SSH by
// MusicAppSSHWorker.get_playlist_tracks().
//
// Ported near-verbatim from a script run by hand in Script Editor to
// regenerate src/playlist.json -- same field shape (Name/Index/Artist/
// PersistentID) so Playlist needs no changes to consume this instead of
// that bundled file. Adapted into this codebase's usual top-level-IIFE
// shape (see recover_airplay_playback.js) rather than the original's
// `function run(argv) {...}`, which only auto-invokes when osascript is
// given a script *file* to run, not when the script text is piped into
// its stdin the way MusicAppSSHWorker does.
//
// MusicAppSSHWorker reads this file and substitutes __PLAYLIST_NAME__
// (JSON-quoted) with the configured Music.app playlist name -- the same
// sshWorker.playlist_name setting recover_airplay_playback.js uses for
// which playlist to start playing, reused here for which playlist to
// enumerate.
(() => {
  const Music = Application("Music");
  const playlistName = "__PLAYLIST_NAME__";

  const playlist = Music.playlists[playlistName];
  const tracks = playlist.tracks;
  const results = [];
  for (let i = 0; i < tracks.length; i++) {
    const track = tracks[i];
    results.push({
      Name: track.name(),
      Index: i,
      Artist: track.artist(),
      PersistentID: track.persistentID(),
    });
  }
  return JSON.stringify(results);
})();
