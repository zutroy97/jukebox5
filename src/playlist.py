import json
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Track:
    name: str
    index: int
    artist: str
    persistent_id: str


class Playlist:
    def __init__(self, tracks: list[dict]):
        self._by_index: dict[int, Track] = {}
        self._by_persistent_id: dict[str, Track] = {}

        for raw in tracks:
            track = Track(
                name=raw["Name"],
                index=raw["Index"],
                artist=raw["Artist"],
                persistent_id=raw["PersistentID"].upper(),
            )
            self._by_index[track.index] = track
            self._by_persistent_id[track.persistent_id] = track

    @classmethod
    def from_file(cls, path: str) -> "Playlist":
        """Build a Playlist from a JSON file in the same shape
        get_playlist_tracks.js returns (a list of {Name, Index, Artist,
        PersistentID} objects). Not used by the live app -- it fetches the
        playlist from Music.app over SSH instead (see
        MusicAppSSHWorker.get_playlist_tracks() and main.py's
        loadPlaylistFromMac()), since an on-device copy can't be kept in
        sync once the filesystem is read-only. Useful for local dev/testing
        without a Mac reachable over SSH -- point it at your own fixture
        file."""
        with open(path, "r") as f:
            return cls(json.load(f))

    def get_by_index(self, index: int) -> Optional[Track]:
        return self._by_index.get(index)

    def get_by_persistent_id(self, persistent_id: str) -> Optional[Track]:
        return self._by_persistent_id.get(persistent_id)

    def get_by_persistent_id_as_int(self, persistent_id: int) -> Optional[Track]:
        return self.get_by_persistent_id(format(persistent_id, "X"))

    def __len__(self) -> int:
        return len(self._by_index)
