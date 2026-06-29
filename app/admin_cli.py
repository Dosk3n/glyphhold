from __future__ import annotations

import argparse
import getpass
import sys

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
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
