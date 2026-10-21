#!/usr/bin/env python3
"""Best-effort pre-publication audit of current Git files and reachable history.

This developer utility is separate from the agent's tool registry. It invokes
only Git, without a shell, and never prints matching content or credential values.
An exit status of zero means these checks found no issue, not that privacy or
secret absence has been mathematically established.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlsplit

MAX_BLOB_BYTES = 2_000_000
MAX_TOTAL_BYTES = 100_000_000
MAX_HISTORY_COMMITS = 1000
MAX_HISTORY_BLOBS = 10_000

KEY_PATTERNS = {
    "api-key-format": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    "github-token-format": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "github-pat-format": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    "aws-access-key-format": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private-key-block": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "machine-absolute-path": re.compile(
        r"/(?:home|Users|root)/[^/\s\"'`<>]+/|/mnt/[a-z]/[^\s\"'`<>]+"
        r"|[A-Za-z]:\\Users\\[^\\\s\"'`<>]+\\"
    ),
}
SENSITIVE_NAME = r"(?:[A-Za-z0-9]+_)*(?:api[_-]?key|access[_-]?token|secret|password|passwd)"
QUOTED_ASSIGNMENT = re.compile(
    rf"\b{SENSITIVE_NAME}\s*[:=]\s*(?:\"([^\"\r\n]+)\"|'([^'\r\n]+)')", re.IGNORECASE
)
ENV_ASSIGNMENT = re.compile(
    rf"^\s*(?:export\s+)?{SENSITIVE_NAME}=([^\r\n#]*)", re.IGNORECASE | re.M
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>`\[\]]+")
RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
PRIVATE_COMPONENTS = {
    ".ssh",
    ".aws",
    ".kube",
    ".azure",
    ".venv",
    ".agent",
    ".local",
    "private",
    "personal",
    "secrets",
    "credentials",
    "downloads",
    "models",
    "node_modules",
}
PRIVATE_FILENAMES = {"id_rsa", "id_ed25519", "credentials.json", "tokens.json", "authorized_keys"}
PRIVATE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key", ".p12", ".pfx"}
PUBLIC_ENV_NAMES = {".env.example", ".env.sample", ".env.template"}


class AuditError(Exception):
    """A safe failure message, with no Git output or file content attached."""


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    rule: str

    def display(self) -> str:
        # Escape control characters in a malicious filename instead of printing them.
        path = json.dumps(self.path, ensure_ascii=False)[1:-1]
        return f"{path}:{self.rule}"


def git(repo: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AuditError("audit:git-command-failed") from None
    if result.returncode:
        raise AuditError("audit:git-command-failed")
    return result.stdout


def is_placeholder(value: str) -> bool:
    value = value.strip().strip("\"'")
    lower = value.casefold()
    return (
        not value
        or lower in {"changeme", "redacted", "none", "null"}
        or lower.startswith(("fixture-", "test-", "private-test-", "example-", "your-", "your_"))
        or lower.startswith(("replace-", "replace_", "not-a-real-", "dummy-"))
        or (value.startswith("<") and value.endswith(">"))
        or (value.startswith("${") and value.endswith("}"))
    )


def path_rules(path: str) -> set[str]:
    parts = PurePosixPath(path).parts
    lower_parts = tuple(part.casefold() for part in parts)
    basename = lower_parts[-1] if lower_parts else ""
    findings: set[str] = set()
    if any(part in PRIVATE_COMPONENTS for part in lower_parts):
        findings.add("private-directory")
    if basename.startswith(".env") and basename not in PUBLIC_ENV_NAMES:
        findings.add("private-env-file")
    if basename in PRIVATE_FILENAMES:
        findings.add("credential-file")
    if PurePosixPath(basename).suffix in PRIVATE_SUFFIXES or re.search(
        r"\.(?:db|sqlite|sqlite3)-(?:wal|shm|journal)$", basename
    ):
        findings.add("private-runtime-or-key-file")
    if PurePosixPath(basename).suffix in {".zip", ".tar", ".gz", ".pt", ".pth", ".safetensors"}:
        findings.add("archive-or-model-artifact")
    return findings


def content_rules(data: bytes, *, env_file: bool = False) -> set[str]:
    text = data.decode("utf-8", errors="replace")
    findings = {name for name, pattern in KEY_PATTERNS.items() if pattern.search(text)}
    for match in QUOTED_ASSIGNMENT.finditer(text):
        value = match.group(1) if match.group(1) is not None else match.group(2)
        if len(value) >= 8 and not is_placeholder(value):
            findings.add("credential-literal")
    if env_file:
        for match in ENV_ASSIGNMENT.finditer(text):
            value = match.group(1).strip().strip("\"'")
            if value and not is_placeholder(value):
                findings.add("credential-literal")
    for match in URL_PATTERN.finditer(text):
        try:
            parsed = urlsplit(match.group())
            host = parsed.hostname or ""
            reserved = host.endswith((".invalid", ".example")) or host in {
                "example.com",
                "example.org",
                "example.net",
            }
            if reserved:
                continue
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if (
                address is not None and any(address in network for network in RFC1918_NETWORKS)
            ) or (host.endswith((".internal", ".corp", ".lan"))):
                findings.add("private-service-url")
            if parsed.password:
                findings.add("credential-in-url")
            for name, value in parse_qsl(parsed.query):
                if re.fullmatch(SENSITIVE_NAME, name, re.IGNORECASE) and not is_placeholder(value):
                    findings.add("credential-in-url")
        except ValueError:
            continue  # Prose can contain incomplete URLs; this is not a syntax checker.
    return findings


@dataclass
class Audit:
    repo: Path
    findings: set[Finding] = field(default_factory=set)
    scanned_files: int = 0
    scanned_history_blobs: int = 0
    scanned_bytes: int = 0

    def add(self, path: str, rules: set[str]) -> None:
        self.findings.update(Finding(path, rule) for rule in rules)

    def inspect(self, label: str, path: str, data: bytes) -> None:
        self.add(label, path_rules(path))
        if len(data) > MAX_BLOB_BYTES:
            self.add(label, {"blob-size-limit"})
            return
        self.scanned_bytes += len(data)
        if self.scanned_bytes > MAX_TOTAL_BYTES:
            raise AuditError("audit:total-byte-limit")
        self.add(label, content_rules(data, env_file=PurePosixPath(path).name.startswith(".env")))

    def inspect_worktree(self, paths: list[str], prefix: str) -> None:
        for name in paths:
            self.add(f"{prefix}/{name}", path_rules(name))
            path = self.repo / name
            try:
                current = self.repo
                if any(
                    (current := current / part).is_symlink() for part in PurePosixPath(name).parts
                ):
                    self.add(f"{prefix}/{name}", {"symlink-review-required"})
                    continue
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    self.add(f"{prefix}/{name}", {"symlink-review-required"})
                    continue
                if not stat.S_ISREG(info.st_mode):
                    self.add(f"{prefix}/{name}", {"nonregular-file"})
                    continue
                if info.st_size > MAX_BLOB_BYTES:
                    self.add(f"{prefix}/{name}", {"blob-size-limit"})
                    continue
                with path.open("rb") as stream:
                    data = stream.read(MAX_BLOB_BYTES + 1)
                self.inspect(f"{prefix}/{name}", name, data)
                self.scanned_files += 1
            except FileNotFoundError:
                continue  # An unstaged deletion is still inspected in the staged/history modes.
            except OSError:
                self.add(f"{prefix}/{name}", {"unreadable-file"})

    def inspect_git_blob(self, label: str, path: str, oid: str) -> None:
        size = int(git(self.repo, "cat-file", "-s", oid))
        if size > MAX_BLOB_BYTES:
            self.add(label, path_rules(path) | {"blob-size-limit"})
            return
        self.inspect(label, path, git(self.repo, "cat-file", "blob", oid))

    def staged(self) -> list[str]:
        paths: list[str] = []
        for entry in git(self.repo, "ls-files", "--stage", "-z").split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, oid, stage = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8", errors="surrogateescape")
            paths.append(path)
            label = f"staged/{path}"
            if stage != "0":
                self.add(label, {"unmerged-index"})
            elif mode == "120000":
                self.add(label, path_rules(path) | {"symlink-review-required"})
            elif mode == "160000":
                self.add(label, {"submodule-review-required"})
            else:
                self.inspect_git_blob(label, path, oid)
        return sorted(set(paths))

    def history(self) -> None:
        commits = git(self.repo, "rev-list", "--all").decode("ascii").splitlines()
        if len(commits) > MAX_HISTORY_COMMITS:
            raise AuditError("audit:history-commit-limit")
        seen: set[tuple[str, str]] = set()
        blobs: set[str] = set()
        for commit in commits:
            emails = git(self.repo, "show", "-s", "--format=%ae%n%ce", commit).decode().splitlines()
            for email in emails:
                if not (
                    email.endswith("@users.noreply.github.com")
                    or email == "noreply@github.com"
                    or email.endswith(("@example.invalid", "@example.com"))
                ):
                    self.add(f"history/commit-{commit[:12]}", {"personal-author-email"})
            for entry in git(self.repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
                if not entry:
                    continue
                metadata, raw_path = entry.split(b"\t", 1)
                mode, kind, raw_oid = metadata.decode("ascii").split()
                path = raw_path.decode("utf-8", errors="surrogateescape")
                label = f"history/{commit[:12]}/{path}"
                self.add(label, path_rules(path))
                if mode == "120000":
                    self.add(label, {"symlink-review-required"})
                    continue
                if kind != "blob":
                    self.add(label, {"submodule-review-required"})
                    continue
                if (raw_oid, path) in seen:
                    continue
                seen.add((raw_oid, path))
                blobs.add(raw_oid)
                if len(blobs) > MAX_HISTORY_BLOBS:
                    raise AuditError("audit:history-blob-limit")
                self.inspect_git_blob(label, path, raw_oid)
        self.scanned_history_blobs = len(blobs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--tracked", action="store_true", help="Inspect tracked working-tree files")
    parser.add_argument("--staged", action="store_true", help="Inspect the complete current index")
    parser.add_argument(
        "--include-untracked", action="store_true", help="Inspect nonignored candidates"
    )
    parser.add_argument(
        "--history", action="store_true", help="Inspect every reachable commit tree"
    )
    options = parser.parse_args(argv)
    if not options.tracked and not options.staged:
        options.tracked = options.staged = True
    try:
        repo = Path(git(options.repo, "rev-parse", "--show-toplevel").decode().strip())
        audit = Audit(repo)
        if options.staged:
            tracked = audit.staged()
        else:
            tracked = [
                name.decode("utf-8", errors="surrogateescape")
                for name in git(repo, "ls-files", "-z").split(b"\0")
                if name
            ]
        if options.tracked:
            audit.inspect_worktree(tracked, "tracked")
        if options.include_untracked:
            untracked = [
                name.decode("utf-8", errors="surrogateescape")
                for name in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(
                    b"\0"
                )
                if name
            ]
            audit.inspect_worktree(untracked, "untracked")
        if options.history:
            audit.history()
    except (AuditError, ValueError, UnicodeError):
        print("audit:scan-failed-or-resource-limit", file=sys.stderr)
        return 2
    for finding in sorted(audit.findings):
        print(finding.display())
    if audit.findings:
        print(f"Privacy audit found {len(audit.findings)} issue(s); matching values are withheld.")
        return 1
    print(
        "Privacy audit passed: "
        f"{audit.scanned_files} working files, {audit.scanned_history_blobs} historical blobs; "
        "best-effort checks only."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
