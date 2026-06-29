# Backup And Restore

Glyph Hold stores its state in SQLite. In Docker, the database should live under
`/data` inside the container.

Back up the whole data directory or volume, not only `glyphhold.sqlite`. SQLite
may also have `glyphhold.sqlite-wal` and `glyphhold.sqlite-shm` files.

Back up both:

- the SQLite data directory or Docker volume
- the `GLYPHHOLD_ENCRYPTION_KEY` value from your `.env` file or container config

If you lose or change the encryption key, existing secret values cannot be
decrypted.

## Docker Compose

With the compose example, data is stored in `./data` next to
`docker-compose.yml`.

Stop Glyph Hold:

```bash
docker compose down
```

Create a backup:

```bash
tar -czf glyphhold-data-backup.tgz data .env
```

Start Glyph Hold again:

```bash
docker compose up -d
```

Restore from a backup:

```bash
docker compose down
rm -rf data
tar -xzf glyphhold-data-backup.tgz
docker compose up -d
```

## Docker Named Volume

If you started Glyph Hold with `-v glyphhold-data:/data`, create a backup with:

```bash
docker stop glyphhold
docker run --rm \
  -v glyphhold-data:/data:ro \
  -v "$PWD":/backup \
  busybox \
  tar -czf /backup/glyphhold-data-backup.tgz -C /data .
docker start glyphhold
```

Restore a named volume backup:

```bash
docker stop glyphhold
docker rm glyphhold
docker volume rm glyphhold-data
docker volume create glyphhold-data
docker run --rm \
  -v glyphhold-data:/data \
  -v "$PWD":/backup \
  busybox \
  tar -xzf /backup/glyphhold-data-backup.tgz -C /data
```

Then recreate the Glyph Hold container with the same `docker run` command and
the same `GLYPHHOLD_ENCRYPTION_KEY` value.

## Before Upgrading

1. Stop Glyph Hold.
2. Back up the data directory or named volume.
3. Back up the encryption key separately.
4. Change the image tag.
5. Start Glyph Hold.
6. Open `http://localhost:5995` and check `/api/v1/health`.

Startup applies pending database migrations automatically.

## After Restore Or Upgrade

Open:

```text
http://localhost:5995/api/v1/health
```

Check that `status` is `ok`, `database` is `ok`, and `schema_version` is the
expected version for the image you are running. Then sign in to the dashboard
and confirm that memories, API keys, and secrets metadata are present.

To verify secret restore, reveal one known non-critical secret. If it does not
decrypt, stop Glyph Hold and restore the original `GLYPHHOLD_ENCRYPTION_KEY`.
