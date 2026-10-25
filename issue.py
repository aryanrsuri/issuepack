#!/usr/bin/env python3
"""Small, repo-local issue tracker. No runtime dependencies."""

import argparse
import os
import sys
from pathlib import Path


def positive_int(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def title_text(value):
    if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("title must be a nonempty, single line of text")
    return value.strip()


def issue_directory():
    current = Path.cwd()
    for parent in (current, *current.parents):
        if (parent / ".git").exists() or (parent / ".issues").exists():
            return parent / ".issues"
    return current / ".issues"


def issue_ids(directory):
    """Scan names only; allocation never reads issue contents."""
    try:
        with os.scandir(directory) as entries:
            numbers = []
            for entry in entries:
                stem = entry.name[:-4]
                if not entry.name.endswith(".txt") or not stem.isascii() or not stem.isdigit():
                    continue
                number = int(stem)
                if number > 0 and stem == str(number) and entry.is_file(follow_symlinks=False):
                    numbers.append(number)
            return numbers
    except FileNotFoundError:
        return []


def read_issue(path, include_body=True):
    with path.open(encoding="utf-8") as source:
        fields = {}
        for key in ("I", "D", "S", "T"):
            line = source.readline()
            if not line.startswith(key + "="):
                raise ValueError(f"{path}: expected {key}= header")
            fields[key] = line[2:].rstrip("\n")
        if fields["I"] != path.stem or not fields["D"]:
            raise ValueError(f"{path}: invalid ID or creation date")
        if fields["S"] not in ("open", "closed"):
            raise ValueError(f"{path}: status must be open or closed")
        title_text(fields["T"])
        if include_body:
            if source.readline() not in ("", "\n"):
                raise ValueError(f"{path}: expected a blank line before the description")
            return fields, source.read()
        return fields, ""


def write_issue(path, fields, body):
    text = "".join(f"{key}={fields[key]}\n" for key in ("I", "D", "S", "T"))
    path.write_text(text + "\n" + body, encoding="utf-8")


def save_issue(path, draft, original):
    """Serialize the comparison and replacement, without locking the editor."""
    lock = path.with_suffix(".lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError(f"issue #{path.stem} is being saved; retry (lock: {lock})") from None
    try:
        if path.read_bytes() != original:
            raise ValueError(f"issue #{path.stem} changed during editing; retry your edit")
        os.replace(draft, path)
    finally:
        lock.rmdir()


def list_issues(directory, args):
    found = False
    query = args.query.casefold() if args.query else ""
    for number in sorted(issue_ids(directory)):
        fields, body = read_issue(directory / f"{number}.txt", include_body=bool(query))
        if query and query not in fields["T"].casefold() and query not in body.casefold():
            continue
        if args.status is None or fields["S"] == args.status:
            if not found:
                print(f"{'ID':>5}  {'STATUS':6}  TITLE")
                found = True
            print(f"{number:>5}  {fields['S']:6}  {fields['T']}")
    if not found:
        if query:
            print("No matching issues." if args.status is None else f"No matching {args.status} issues.")
        else:
            print("No issues." if args.status is None else f"No {args.status} issues.")
    return 0


def new_issue(directory, args):
    from datetime import datetime, timezone
    from tempfile import TemporaryDirectory

    title = title_text(args.title)
    directory.mkdir(exist_ok=True)
    number = max(issue_ids(directory), default=0) + 1
    fields = {
        "I": str(number),
        "D": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "S": "open",
        "T": title,
    }
    # Publish a complete file atomically. Exclusive links also reserve IDs when
    # multiple processes create issues at the same time.
    with TemporaryDirectory(prefix=".new-", dir=directory) as temporary:
        draft = Path(temporary) / "issue.txt"
        while True:
            fields["I"] = str(number)
            write_issue(draft, fields, args.message or "")
            try:
                os.link(draft, directory / f"{number}.txt")
                break
            except FileExistsError:
                number += 1
    print(f"Created #{number}: {title}")
    return 0


def edit_issue(directory, args):
    import shlex
    import subprocess
    from tempfile import TemporaryDirectory

    path = directory / f"{args.id}.txt"
    try:
        original = path.read_bytes()
    except FileNotFoundError:
        raise ValueError(f"issue #{args.id} does not exist") from None
    fields, body = read_issue(path)
    if args.title is not None:
        fields["T"] = title_text(args.title)
    if args.status is not None:
        fields["S"] = args.status
    if args.message:
        if body and not body.endswith("\n"):
            body += "\n"
        body += args.message
    with TemporaryDirectory(prefix=".edit-", dir=directory) as temporary:
        draft = Path(temporary) / path.name
        write_issue(draft, fields, body)
        if args.title is None and args.status is None and args.message is None:
            editor = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
            if not editor:
                raise ValueError("set VISUAL or EDITOR to an editor command")
            result = subprocess.run([*editor, str(draft)])
            if result.returncode:
                raise ValueError(f"editor exited with status {result.returncode}; issue unchanged")
        updated, _ = read_issue(draft)
        if updated["D"] != fields["D"]:
            raise ValueError("creation date cannot be changed; issue unchanged")
        if draft.read_bytes() == original:
            print(f"Unchanged #{args.id}.")
            return 0
        save_issue(path, draft, original)
    print(f"Updated #{args.id}: {updated['T']}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="issuepack",
        description="Pack issues into your repo. Commit them with Git.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    parsers = {}
    for name, description, handler in (
        ("ls", "List issues.", list_issues),
        ("new", "Create an issue.", new_issue),
        ("edit", "Edit an issue using flags or $VISUAL / $EDITOR (default: vi).", edit_issue),
        ("help", "Show help for a command.", None),
    ):
        command = commands.add_parser(name, help=description, description=description, allow_abbrev=False)
        command.set_defaults(handler=handler)
        parsers[name] = command
    parsers["ls"].add_argument(
        "query", nargs="?", help="search titles and descriptions (case-insensitive literal text)"
    )
    parsers["ls"].add_argument(
        "--status", choices=("open", "closed"), default="open", help="filter by status (default: open)"
    )
    parsers["new"].add_argument("title", help="issue title (quote multiple words)")
    parsers["new"].add_argument("-m", "--message", help="issue description")
    parsers["edit"].add_argument("id", type=positive_int, help="issue number")
    parsers["edit"].add_argument("--title", help="replace the title")
    parsers["edit"].add_argument("--status", choices=("open", "closed"), help="set the status")
    parsers["edit"].add_argument("-m", "--message", help="append to the description")
    parsers["help"].add_argument("topic", choices=tuple(parsers), nargs="?", help="command to explain")
    return parser, parsers


def main(argv=None):
    parser, parsers = build_parser()
    args = parser.parse_args(argv)
    if args.command is None or args.command == "help":
        topic = getattr(args, "topic", None)
        (parsers[topic] if topic else parser).print_help()
        return 0
    try:
        return args.handler(issue_directory(), args)
    except (OSError, ValueError) as error:
        print(f"issuepack: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("issuepack: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
