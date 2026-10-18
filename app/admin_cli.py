from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from app.core.auth import hash_password
from app.storage.migrations import apply_migrations
from app.storage.repositories import auth as auth_repo

MIN_PASSWORD_LENGTH = 12


def reset_password(*, username: str | None, password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    apply_migrations()
    admins = auth_repo.list_admin_users()
    if not admins:
        raise RuntimeError("No dashboard admin user exists. Start Glyph Hold and complete first-run setup.")

    selected_username = (username or "").strip()
    if not selected_username:
        if len(admins) > 1:
            names = ", ".join(admin["username"] for admin in admins)
            raise RuntimeError(f"Multiple admin users exist. Choose one with --username. Admins: {names}")
        selected_username = admins[0]["username"]

    if not auth_repo.update_dashboard_password(selected_username, hash_password(password)):
        raise RuntimeError(f'Dashboard admin user "{selected_username}" was not found.')
    return selected_username


def _prompt_password() -> str:
    password = getpass.getpass("New dashboard password: ")
    confirm = getpass.getpass("Confirm dashboard password: ")
    if password != confirm:
        raise ValueError("Passwords do not match.")
    return password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="glyphhold-admin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_parser = subparsers.add_parser(
        "reset-password",
        help="Reset an existing dashboard admin password.",
    )
    reset_parser.add_argument(
        "--username",
        help="Dashboard admin username. Optional when exactly one admin exists.",
    )
    reset_parser.add_argument(
        "--password",
        help="New password. If omitted, the command prompts without echoing input.",
    )
    export_parser = subparsers.add_parser("export-memory", help="Export a source SQLite memory store read-only, excluding secrets.")
    export_parser.add_argument("--database", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    backup_parser = subparsers.add_parser("backup", help="Create a consistent SQLite backup (also preserve your encryption key separately).")
    backup_parser.add_argument("--output", type=Path, required=True)
    secret_parser = subparsers.add_parser("export-secrets", help="Create a passphrase-encrypted transfer of built-in secrets; source key is read from a private file.")
    secret_parser.add_argument("--database", type=Path, required=True)
    secret_parser.add_argument("--key-file", type=Path, required=True)
    secret_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "export-secrets":
            from app.providers.transfer import export_secrets
            from app.storage.upgrade import write_private_json
            password = getpass.getpass("Transfer passphrase (at least 12 characters): ")
            if password != getpass.getpass("Confirm transfer passphrase: "):
                raise ValueError("Passphrases do not match")
            package = export_secrets(args.database, args.key_file.read_text().strip(), password)
            write_private_json(args.output, package)
            print("Encrypted secret transfer created. Import it separately from memories.")
            return 0
        if args.command == "export-memory":
            from app.storage.upgrade import export_legacy_memories, write_private_json
            write_private_json(args.output, export_legacy_memories(args.database))
            print("Memory export created; secrets are excluded.")
            return 0
        if args.command == "backup":
            from app.config import settings
            from app.storage.upgrade import snapshot_database
            snapshot_database(settings.db_path, args.output)
            print("Database backup created. Preserve encryption.key or the external encryption key separately.")
            return 0
        if args.command == "reset-password":
            password = args.password or _prompt_password()
            username = reset_password(username=args.username, password=password)
            print(f'Password reset for dashboard user "{username}".')
            return 0
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
