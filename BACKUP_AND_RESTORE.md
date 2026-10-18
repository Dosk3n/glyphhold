# GH2 Backup and Restore

The default persistent volume contains `glyphhold.sqlite`, its WAL/SHM files,
`encryption.key`, private Codex authentication under `advanced/codex`, and
Bitwarden CLI state. Preserve the entire volume securely. A volume backup can
unlock secrets and use saved account sessions; protect it like credentials.

For a consistent online database snapshot:

```bash
glyphhold-admin backup --output /safe/path/glyphhold-backup.sqlite
```

Also preserve `/data/encryption.key`, or the original externally supplied
`GLYPHHOLD_ENCRYPTION_KEY`. A database snapshot by itself does not include the
installation key or provider login state. Copying only an active SQLite main
file without its WAL is not a valid online backup.

For a full-volume backup, stop only the intended Compose project, archive its
volume preserving ownership/permissions, then restart it. Restore into a new,
empty volume with the service stopped, using the matching database and key.
Test the restored copy before replacing a working installation. Avoid deleting
working volumes as a restore procedure.

Use `docker-compose.gh2-test.yml` with project name `glyphhold2-test` for isolated
rehearsals. Its port5996 and named volume are separate from the running v1
installation on5995. `docker compose down` retains data; `down -v` deletes it.

## Upgrading v1

1. Preserve an independent consistent backup and the original v1 encryption key.
2. Rehearse on a copy in a separate volume; never mount live v1 data in GH2 while
   the old service is using it.
3. Supply the original key when starting GH2 against copied encrypted data.
4. GH2 creates a pre-upgrade database snapshot and applies additive v2 schema.
5. Existing memories/secrets enter restricted Import review ownership. Configure
   spaces and upgraded-client grants before agents connect.
6. Compare counts, representative content, revisions, timestamps and search.
   Explicitly reveal a disposable known secret to verify decryption.

A missing or incompatible key must fail instead of silently generating a new
one over encrypted data. A changed key source is not key rotation. The database
and original key must be restored as a matched set. Returning to v1 after new v2
writes requires reconciliation; do not run v1 directly on the migrated database.

## Combining installations

Export memories separately from secrets:

```bash
glyphhold-admin export-memory --database /copy/source.sqlite --output memories.json
```

Import through the Migration page with a stable namespace for each source and
an explicit destination space. Preview first; repeat imports are safe, changed
sources produce conflicts rather than overwrite later edits. Unknown ownership
belongs in Import review. Classifying/merging imported memories is a separate,
optional Advanced Memory activity after faithful import.

To transfer built-in secrets, use a private file containing the source's
original encryption key and create a separately encrypted package:

```bash
glyphhold-admin export-secrets --database /copy/source.sqlite --key-file /private/source.key --output secrets.encrypted.json
```

The command prompts for a transfer passphrase without echoing it. Import the
package in the separate encrypted-secret section of Migration, entering that
passphrase, source namespace and destination space. Preview lists metadata only;
values are reencrypted under the destination installation key. Keep source
backups until successful validation. External Bitwarden/Vaultwarden handles must
be deliberately relinked to selected provider accounts/items/fields; toggling a
provider is never migration.


GH2 security upgrades derive dashboard signing keys from the installation encryption key and remove the old database signing secret. Existing dashboard cookies expire once; user passwords are retained. If secret storage is explicitly disabled, also preserve the private session.key file in the data directory. Key files must be regular files owned by the service user; startup repairs permissions to0600 and rejects symbolic links. Legacy secret-import hashes are protected during migration; already copied older backups remain sensitive and cannot be retroactively changed.
