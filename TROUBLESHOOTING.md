# Troubleshooting

## Check Health

Open:

```text
http://localhost:5995/api/v1/health
```

A healthy service returns `status: ok`, the app version, the database status,
the schema version, and whether secret storage is enabled.

## View Logs

For a container named `glyphhold`:

```bash
docker logs glyphhold
```

With Docker Compose:

```bash
docker compose logs glyphhold
```

## Port 5995 Is Already In Use

Only one service can bind to `5995` on the host. Stop the other service or map
Glyph Hold to a different host port:

```yaml
ports:
  - "5996:5995"
```

Then open `http://localhost:5996`.

## Dashboard Setup Does Not Appear

Open `http://localhost:5995` in a browser. Glyph Hold redirects new installs to
`/setup`.

If setup still does not appear, check:

- the container is running
- the port mapping is correct
- `/api/v1/health` reports `database: ok`

## Lost Dashboard Password

Alpha releases do not include a password reset screen yet.

If you cannot sign in, stop the container, back up the data directory, and start
with a new empty database. This removes dashboard users, API keys, memories,
secrets, and audit events.

## Secret Storage Is Disabled

Secret create, reveal, and env endpoints require:

```text
GLYPHHOLD_ENCRYPTION_KEY=<long-random-value>
```

Generate one with:

```bash
openssl rand -hex 32
```

Keep the same value across restarts and upgrades.

## Existing Secrets Will Not Decrypt

This usually means the encryption key changed.

Restore the original `GLYPHHOLD_ENCRYPTION_KEY` value and restart Glyph Hold.
If the original key is lost, existing stored secret values cannot be recovered.

## Image Pull Fails

Use the lowercase image name:

```text
ghcr.io/dosk3n/glyphhold:0.1.0-alpha
```

Prerelease tags do not move `latest`, so pin the exact version shown in the
README.
