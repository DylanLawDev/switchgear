from switchgear.config import Settings
from switchgear.storage.base import Storage
from switchgear.storage.memory import MemoryStorage


def get_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "firestore":
        from switchgear.storage.firestore import FirestoreStorage

        return FirestoreStorage()
    if settings.storage_backend == "memory":
        return MemoryStorage(path=f"{settings.state_dir}/storage.json")
    from switchgear.storage.sqlite import SQLiteStorage

    return SQLiteStorage(settings.sqlite_path)
