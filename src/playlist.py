import json
import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Track:
    name: str
    index: int
    artist: str
    persistent_id: str


class Playlist:
    def __init__(self, path: str = None):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "playlist.json")

        with open(path, "r") as f:
            raw_tracks = json.load(f)

        self._by_index: dict[int, Track] = {}
        self._by_persistent_id: dict[str, Track] = {}

        for raw in raw_tracks:
            track = Track(
                name=raw["Name"],
                index=raw["Index"],
                artist=raw["Artist"],
                persistent_id=raw["PersistentID"].upper(),
            )
            self._by_index[track.index] = track
            self._by_persistent_id[track.persistent_id] = track

    def get_by_index(self, index: int) -> Optional[Track]:
        return self._by_index.get(index)

    def get_by_persistent_id(self, persistent_id: str) -> Optional[Track]:
        return self._by_persistent_id.get(persistent_id)

    def get_by_persistent_id_as_int(self, persistent_id: int) -> Optional[Track]:
        return self.get_by_persistent_id(format(persistent_id, "X"))

    def __len__(self) -> int:
        return len(self._by_index)
