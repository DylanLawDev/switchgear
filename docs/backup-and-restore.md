# Backup and restore

SQLite runs in WAL mode. Use SQLite's online backup command while the service is
running, or stop the container before copying files.

```sh
docker compose exec agent sqlite3 /data/switchgear.sqlite3 ".backup '/data/backup.sqlite3'"
docker compose cp agent:/data/backup.sqlite3 ./backup.sqlite3
```

If `sqlite3` is not installed in the image, stop the service and copy the whole named
volume with a temporary utility container. Back up all of `/data`, not only the
database, because resumes, screenshots, and other artifacts are files.

To restore, stop the service, replace the contents of `/data`, preserve ownership for
UID/GID 10001, and restart. Test `/healthz`, login, stored conversations, schedules,
and an artifact after every restore exercise.

Legacy JSON users can run:

```sh
docker compose run --rm switchgear switchgear import-storage-json \
  /data/storage.json --database /data/switchgear.sqlite3
```
