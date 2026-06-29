# Backup And Restore

Glyph Hold stores its state in SQLite. In Docker, the database should live under
`/data` inside the container.

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
docker volume rm glyphhold-data
docker volume create glyphhold-data
docker run --rm \
  -v glyphhold-data:/data \
  -v "$PWD":/backup \
  busybox \
  tar -xzf /backup/glyphhold-data-backup.tgz -C /data
docker start glyphhold
```

## Before Upgrading

1. Stop Glyph Hold.
2. Back up the data directory or named volume.
3. Back up the encryption key separately.
4. Change the image tag.
5. Start Glyph Hold.
6. Open `http://localhost:5995` and check `/api/v1/health`.

Startup applies pending database migrations automatically.
