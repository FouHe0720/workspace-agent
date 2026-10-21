"""Bounded filesystem access through pinned, no-follow directory descriptors.

The workspace must already exist and be explicitly selected by the caller. File
contents are untrusted data; this module never interprets them as instructions.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path

MAX_FILE_BYTES = 128 * 1024
MAX_DIRECTORY_ENTRIES = 200
MAX_SCAN_ENTRIES = 500
MAX_SCAN_FILES = 200
MAX_SCAN_DEPTH = 8


class SandboxError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _private_name(name: str) -> bool:
    lower = name.lower()
    return (
        name.startswith(".")
        or lower
        in {
            "env",
            "credentials",
            "credentials.json",
            "secrets",
            "secrets.json",
            "token",
            "tokens",
            "id_rsa",
            "id_ed25519",
            "authorized_keys",
            "known_hosts",
        }
        or lower.endswith((".env", ".pem", ".key"))
    )


def _filesystem_error(exc: OSError) -> SandboxError:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        return SandboxError(
            "SANDBOX_VIOLATION", "Symlinks and non-directory path components are denied."
        )
    if exc.errno == errno.ENOENT:
        return SandboxError("FILE_NOT_FOUND", "The requested workspace path does not exist.", True)
    if exc.errno == errno.EEXIST:
        return SandboxError("OVERWRITE_DENIED", "The destination already exists.")
    if exc.errno in {errno.EACCES, errno.EPERM}:
        return SandboxError("PERMISSION_DENIED", "The workspace path is not accessible.")
    return SandboxError("FILESYSTEM_ERROR", "The workspace operation failed.", True)


class Sandbox:
    """A single authorized existing directory, never a whole home or repository."""

    def __init__(self, root: Path | str) -> None:
        self._root_fd = -1
        candidate = Path(root).expanduser().absolute()
        # Inspect before resolve(): resolve alone silently accepts a symlink root.
        try:
            for component in (candidate, *candidate.parents):
                if component.is_symlink():
                    raise SandboxError(
                        "SANDBOX_VIOLATION", "The workspace root cannot contain symlinks."
                    )
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise _filesystem_error(exc) from exc
        repo_root = Path(__file__).resolve().parents[2]
        forbidden = {
            Path("/"),
            Path.home().resolve(),
            repo_root,
            Path("/home"),
            Path("/root"),
            Path("/tmp"),
        }
        system_roots = (
            "/etc",
            "/proc",
            "/sys",
            "/dev",
            "/usr",
            "/bin",
            "/sbin",
            "/boot",
            "/run",
            "/lib",
            "/lib64",
            "/var",
        )
        if (
            resolved in forbidden
            or resolved.parent == Path("/home")
            or any(resolved == Path(p) or Path(p) in resolved.parents for p in system_roots)
            or any(_private_name(part) for part in resolved.parts[1:])
            or (resolved / ".git").exists()
        ):
            raise SandboxError(
                "SANDBOX_VIOLATION",
                "Select a dedicated workspace, not a home, repository, or system directory.",
            )
        try:
            self._root_fd = os.open(
                resolved, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            self._root_identity = self._identity(os.fstat(self._root_fd))
        except OSError as exc:
            raise _filesystem_error(exc) from exc
        self.root = resolved

    def close(self) -> None:
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1

    def __del__(self) -> None:
        self.close()

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int]:
        return info.st_dev, info.st_ino

    def _check_root(self) -> None:
        try:
            info = self.root.stat(follow_symlinks=False)
            if (
                self._root_fd < 0
                or not stat.S_ISDIR(info.st_mode)
                or self._identity(info) != self._root_identity
                or self.root.resolve(strict=True) != self.root
            ):
                raise SandboxError(
                    "SANDBOX_VIOLATION", "The authorized workspace root has changed."
                )
        except OSError as exc:
            raise _filesystem_error(exc) from exc

    def relative_parts(self, relative_path: str, *, allow_root: bool = False) -> tuple[str, ...]:
        if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 1024:
            raise SandboxError(
                "SANDBOX_VIOLATION", "A bounded relative workspace path is required."
            )
        if any(ord(char) < 32 for char in relative_path) or any(
            char in relative_path for char in "\\%:"
        ):
            raise SandboxError(
                "SANDBOX_VIOLATION", "Encoded, control, and platform-specific paths are denied."
            )
        if relative_path.startswith("/"):
            raise SandboxError("SANDBOX_VIOLATION", "Absolute paths are denied.")
        parts = relative_path.split("/")
        if ".." in parts or any(_private_name(part) for part in parts if part != "."):
            raise SandboxError(
                "SANDBOX_VIOLATION", "Parent traversal and private workspace paths are denied."
            )
        cleaned = tuple(part for part in parts if part not in {"", "."})
        if any(len(part.encode("utf-8")) > 255 for part in cleaned):
            raise SandboxError("SANDBOX_VIOLATION", "A path component is too long.")
        if not cleaned and not allow_root:
            raise SandboxError("SANDBOX_VIOLATION", "A file path is required.")
        return cleaned

    def _directory_fd(self, parts: tuple[str, ...]) -> int:
        self._check_root()
        descriptor = os.dup(self._root_fd)
        try:
            for part in parts:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_fd
            self._verify_directory_location(descriptor, parts)
            return descriptor
        except (OSError, SandboxError) as exc:
            os.close(descriptor)
            if isinstance(exc, SandboxError):
                raise
            raise _filesystem_error(exc) from exc

    def _verify_directory_location(self, descriptor: int, parts: tuple[str, ...]) -> None:
        """Detect renamed ancestors while preserving no-follow lookup semantics.

        Checks surround each operation. A hostile process with the same OS identity
        can still rename between a check and a syscall; that threat needs OS isolation.
        """
        self._check_root()
        comparison_fd = os.dup(self._root_fd)
        try:
            for part in parts:
                child_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=comparison_fd,
                )
                os.close(comparison_fd)
                comparison_fd = child_fd
            if self._identity(os.fstat(comparison_fd)) != self._identity(os.fstat(descriptor)):
                raise SandboxError(
                    "SANDBOX_VIOLATION", "A workspace directory changed during access."
                )
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise SandboxError(
                    "SANDBOX_VIOLATION", "A workspace directory moved during access."
                ) from exc
            raise _filesystem_error(exc) from exc
        finally:
            os.close(comparison_fd)

    @staticmethod
    def _check_regular(info: os.stat_result) -> None:
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SandboxError(
                "SANDBOX_VIOLATION", "Only ordinary files without hard links are allowed."
            )
        if info.st_size > MAX_FILE_BYTES:
            raise SandboxError("RESOURCE_LIMIT", "The file exceeds the workspace byte limit.")

    @staticmethod
    def _read_descriptor(descriptor: int) -> bytes:
        chunks: list[bytes] = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 16384))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > MAX_FILE_BYTES:
            raise SandboxError("RESOURCE_LIMIT", "The file exceeds the workspace byte limit.")
        return content

    def target_exists(self, relative_path: str) -> bool:
        parts = self.relative_parts(relative_path)
        parent_fd = self._directory_fd(parts[:-1])
        try:
            try:
                info = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                self._verify_directory_location(parent_fd, parts[:-1])
                return False
            self._check_regular(info)
            self._verify_directory_location(parent_fd, parts[:-1])
            return True
        except OSError as exc:
            raise _filesystem_error(exc) from exc
        finally:
            os.close(parent_fd)

    def read_bytes(self, relative_path: str) -> bytes:
        parts = self.relative_parts(relative_path)
        parent_fd = self._directory_fd(parts[:-1])
        descriptor = -1
        try:
            descriptor = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            self._verify_directory_location(parent_fd, parts[:-1])
            self._check_regular(os.fstat(descriptor))
            content = self._read_descriptor(descriptor)
            self._verify_directory_location(parent_fd, parts[:-1])
            return content
        except OSError as exc:
            raise _filesystem_error(exc) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent_fd)

    def read_text(self, relative_path: str) -> str:
        content = self.read_bytes(relative_path)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SandboxError("UNSUPPORTED_FILE", "Only UTF-8 text files are supported.") from exc
        if "\x00" in text or any(ord(char) < 32 and char not in "\n\r\t" for char in text):
            raise SandboxError("UNSUPPORTED_FILE", "Binary and control-character files are denied.")
        return text

    def write_text(
        self,
        relative_path: str,
        content: str,
        *,
        overwrite: bool = False,
        expected_sha256: str | None = None,
    ) -> dict:
        raw = content.encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise SandboxError("RESOURCE_LIMIT", "The content exceeds the workspace byte limit.")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in content):
            raise SandboxError(
                "UNSUPPORTED_FILE", "Binary and control-character content is denied."
            )
        parts = self.relative_parts(relative_path)
        parent_fd = self._directory_fd(parts[:-1])
        descriptor = -1
        verification_fd = -1
        try:
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            if overwrite:
                # First try creation, then a no-follow open of an existing file.
                try:
                    descriptor = os.open(
                        parts[-1], flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd
                    )
                except FileExistsError:
                    descriptor = os.open(parts[-1], flags, dir_fd=parent_fd)
            else:
                descriptor = os.open(
                    parts[-1], flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd
                )
            self._verify_directory_location(parent_fd, parts[:-1])
            self._check_regular(os.fstat(descriptor))
            if expected_sha256 is not None:
                previous = self._read_descriptor(descriptor)
                if hashlib.sha256(previous).hexdigest() != expected_sha256:
                    raise SandboxError(
                        "STATE_CONFLICT",
                        "The tool-owned state changed before it could be updated.",
                        True,
                    )
                os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            pending = memoryview(raw)
            while pending:
                written = os.write(descriptor, pending)
                if written <= 0:
                    raise SandboxError(
                        "FILESYSTEM_ERROR", "The workspace write did not complete.", True
                    )
                pending = pending[written:]
            os.fsync(descriptor)
            self._verify_directory_location(parent_fd, parts[:-1])
            verification_fd = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            self._check_regular(os.fstat(verification_fd))
            verified = self._read_descriptor(verification_fd)
            if (
                self._identity(os.fstat(descriptor)) != self._identity(os.fstat(verification_fd))
                or verified != raw
            ):
                raise SandboxError(
                    "VERIFICATION_FAILED", "The written file did not pass content verification."
                )
            self._verify_directory_location(parent_fd, parts[:-1])
            return {
                "path": "/".join(parts),
                "exists": True,
                "verified": True,
                "sha256": hashlib.sha256(verified).hexdigest(),
                "bytes": len(verified),
            }
        except OSError as exc:
            raise _filesystem_error(exc) from exc
        finally:
            for fd in (descriptor, verification_fd, parent_fd):
                if fd >= 0:
                    os.close(fd)

    def list_directory(self, relative_path: str = ".") -> dict:
        parts = self.relative_parts(relative_path, allow_root=True)
        descriptor = self._directory_fd(parts)
        entries: list[dict] = []
        skipped = 0
        scanned = 0
        truncated = False
        try:
            with os.scandir(descriptor) as iterator:
                for entry in iterator:
                    scanned += 1
                    if scanned > MAX_DIRECTORY_ENTRIES:
                        truncated = True
                        break
                    if _private_name(entry.name) or entry.is_symlink():
                        skipped += 1
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                            skipped += 1
                            continue
                        entries.append(
                            {
                                "name": entry.name,
                                "path": "/".join((*parts, entry.name)),
                                "type": "directory" if stat.S_ISDIR(info.st_mode) else "file",
                                "size": info.st_size,
                            }
                        )
                    except OSError:
                        skipped += 1
            self._verify_directory_location(descriptor, parts)
        except OSError as exc:
            raise _filesystem_error(exc) from exc
        finally:
            os.close(descriptor)
        return {
            "path": "/".join(parts) or ".",
            "entries": sorted(entries, key=lambda entry: entry["name"]),
            "skipped": skipped,
            "scanned_entries": min(scanned, MAX_DIRECTORY_ENTRIES),
            "truncated": truncated,
        }

    def scan_files(self) -> dict:
        """Count every observed entry, including denied and unreadable entries."""
        self._check_root()
        pending: list[tuple[str, ...]] = [()]
        files: list[str] = []
        scanned = skipped = 0
        truncated = False
        while pending and scanned < MAX_SCAN_ENTRIES and len(files) < MAX_SCAN_FILES:
            parts = pending.pop()
            descriptor = -1
            try:
                descriptor = self._directory_fd(parts)
                with os.scandir(descriptor) as iterator:
                    for entry in iterator:
                        scanned += 1
                        if _private_name(entry.name) or entry.is_symlink():
                            skipped += 1
                        else:
                            try:
                                info = entry.stat(follow_symlinks=False)
                                child = (*parts, entry.name)
                                if stat.S_ISDIR(info.st_mode):
                                    if len(child) < MAX_SCAN_DEPTH:
                                        pending.append(child)
                                    else:
                                        skipped += 1
                                        truncated = True
                                elif stat.S_ISREG(info.st_mode):
                                    files.append("/".join(child))
                                else:
                                    skipped += 1
                            except OSError:
                                skipped += 1
                        if scanned >= MAX_SCAN_ENTRIES or len(files) >= MAX_SCAN_FILES:
                            truncated = True
                            break
            except (SandboxError, OSError):
                skipped += 1
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        return {
            "files": files,
            "scanned_entries": scanned,
            "skipped": skipped,
            "truncated": truncated or bool(pending),
        }
