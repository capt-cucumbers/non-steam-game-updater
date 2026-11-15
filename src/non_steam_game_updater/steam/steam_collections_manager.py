import base64
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from non_steam_game_updater.core.helpers import detect_steam3_id, detect_steam_dir, is_steam_running
from non_steam_game_updater.core.utils import backup_file, read_json, write_json

logger = logging.getLogger(__name__)


class SteamCollectionsManager:
    """Manage Steam collections stored in cloud storage."""

    def __init__(
        self,
        steam_dir: str | Path | None = None,
        steam3_id: str | None = None,
        check_steam_running: bool = True,
    ) -> None:
        if check_steam_running and is_steam_running():
            raise RuntimeError("Steam is currently running. Please close Steam before modifying non-steam games.")

        self.steam_dir = str(steam_dir) if steam_dir else detect_steam_dir()
        self.steam3_id = steam3_id or detect_steam3_id(self.steam_dir)

        self.userdata_dir = (Path(self.steam_dir) / "userdata" / self.steam3_id).as_posix()
        self.cloudstorage_dir = (Path(self.userdata_dir) / "config" / "cloudstorage").as_posix()
        self.namespaces_path = (Path(self.cloudstorage_dir) / "cloud-storage-namespaces.json").as_posix()

        self.active_namespace: int = 1
        self.steam_cloud_data: list[Any] = []
        self.scm_cloud_data: list[Any] = []
        self.collections: dict[str, dict[str, Any]] = {}

        self.read()

    def read(self) -> dict[str, dict[str, Any]]:
        """Read collections from cloud storage and return them keyed by collection ID."""
        self.active_namespace = self._get_active_namespace()

        cloud_storage_path = Path(self.cloudstorage_dir) / f"cloud-storage-namespace-{self.active_namespace}.json"
        if not cloud_storage_path.exists():
            raise FileNotFoundError(f"Cloud storage file not found: {cloud_storage_path}")

        cloud_data = read_json(cloud_storage_path)

        # Parse and separate cloud data
        self.steam_cloud_data, self.scm_cloud_data = self._parse_cloud_data(cloud_data)

        # Build collections dictionary
        self.collections = self._build_collections_dict()

        return self.collections

    def get(self, collection_id: str) -> dict[str, Any] | None:
        """Return a collection by ID, or None if not found."""
        return self.collections.get(collection_id)

    def update(
        self,
        collection_id: str,
        collection_name: str,
        added: list[int] | None = None,
        removed: list[int] | None = None,
        merge: bool = False,
    ) -> None:
        """Add or update a collection, optionally merging App IDs with the existing entry."""
        if not collection_id.startswith("scm-"):
            raise ValueError(f"Collection ID must start with 'scm-'. Got: '{collection_id}'")

        if added is None:
            added = []
        if removed is None:
            removed = []

        if merge and collection_id in self.collections:
            existing = self.collections[collection_id]
            added = list(set(existing.get("added", []) + added))
            removed = list(set(existing.get("removed", []) + removed))

        self.collections[collection_id] = {
            "id": collection_id,
            "name": collection_name,
            "added": added,
            "removed": removed,
        }

        logger.info(f"Updated collection '{collection_name}' with collection ID {collection_id}")

    def remove(self, collection_id: str) -> bool:
        """Remove a collection, returning whether it existed."""
        if collection_id in self.collections:
            del self.collections[collection_id]
            return True
        return False

    def save(self) -> None:
        """Save collections to cloud storage, marking removed SCM collections as deleted."""
        cloud_storage_path = Path(self.cloudstorage_dir) / f"cloud-storage-namespace-{self.active_namespace}.json"
        if not cloud_storage_path.exists():
            raise FileNotFoundError(f"Cloud storage file not found: {cloud_storage_path}")

        timestamp = int(datetime.now().timestamp())

        scm_cloud_data = []

        # 1. Mark deleted SCM entries
        scm_keys = {f"user-collections.{c_id}" for c_id in self.collections if c_id.startswith("scm-")}
        for item in self.scm_cloud_data:
            key = item[0]
            if key not in scm_keys:
                entry = item[1].copy()
                entry["timestamp"] = timestamp
                entry["is_deleted"] = True
                scm_cloud_data.append([key, entry])

        # 2. Update/add current collections
        for c_id, collection_data in self.collections.items():
            if not c_id.startswith("scm-"):
                continue

            key = f"user-collections.{c_id}"
            entry = {
                "key": key,
                "timestamp": timestamp,
                "value": json.dumps(collection_data, separators=(",", ":")),
                "version": str(timestamp),
                "conflictResolutionMethod": "custom",
                "strMethodId": "union-collections",
            }
            scm_cloud_data.append([key, entry])

        # 3. Merge with Steam data
        cloud_data = self.steam_cloud_data + scm_cloud_data

        # 4. Write collections to cloud storage data
        backup_file(cloud_storage_path)
        write_json(cloud_storage_path, cloud_data)

    def find_collection_by_name(self, collection_name: str) -> str | None:
        """Return the collection ID matching a display name, or None if not found."""
        search_name = collection_name.lower()

        for collection_id, data in self.collections.items():
            compare_name = data.get("name", "").lower()
            if compare_name == search_name:
                return collection_id

        return None

    def _build_collections_dict(self) -> dict[str, dict[str, Any]]:
        """Build the collections dict from parsed SCM cloud data."""
        collections = {}
        for item in self.scm_cloud_data:
            if not item[1].get("is_deleted"):
                collection_id = item[0].removeprefix("user-collections.")
                try:
                    collection_value = json.loads(item[1]["value"])
                    collections[collection_id] = collection_value
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"Failed to parse collection {collection_id}: {e}")

        return collections

    def _get_active_namespace(self) -> int:
        """Return the cloud storage namespace with the highest non-zero version."""
        if not Path(self.namespaces_path).exists():
            return 1  # Default

        namespaces = read_json(self.namespaces_path)

        try:
            # Sort by version (second element), descending
            sorted_ns = sorted(namespaces, key=lambda x: int(x[1]), reverse=True)
            # Return first namespace with non-zero version
            if sorted_ns and sorted_ns[0][1] != "0":
                return sorted_ns[0][0]

        except Exception as e:
            logger.error(f"Error: Could not parse namespaces file: {e}")

        return 1

    @staticmethod
    def create_scm_collection_id(name: str) -> str:
        """Return a URL-safe SCM collection ID for a display name (scm-{base64})."""
        encoded = base64.b64encode(name.encode("utf-8")).decode("ascii")
        safe_encoded = encoded.replace("+", "-").replace("/", "_").replace("=", "")
        return f"scm-{safe_encoded}"

    @staticmethod
    def _parse_cloud_data(cloud_data: list[Any]) -> tuple[list[Any], list[Any]]:
        """Separate raw cloud storage data into Steam and SCM collection entries."""
        steam_cloud_data = []
        scm_cloud_data = []

        for item in cloud_data:
            # Preserve malformed entries in steam_cloud_data
            if not (isinstance(item, list) and len(item) >= 2):
                steam_cloud_data.append(item)
                continue

            # Also preserve non user-collections entries in steam_cloud_data
            if not item[0].startswith("user-collections.scm-"):
                steam_cloud_data.append(item)
                continue

            scm_cloud_data.append(item)

        return steam_cloud_data, scm_cloud_data

    def __enter__(self) -> "SteamCollectionsManager":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is None:
            self.save()
