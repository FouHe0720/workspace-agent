"""Exercise the publication audit against isolated, disposable Git repositories."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "privacy_check.py"


def git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        timeout=10,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Privacy Fixture")
    git(root, "config", "user.email", "1+fixture@users.noreply.github.com")
    git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("Public fixture data.\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "Public fixture")
    return root


def audit(repo: Path, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *options],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_public_placeholders_and_security_fixtures_pass(repo: Path) -> None:
    (repo / ".env.example").write_text("WA_API_KEY=\nWA_MODEL=\n", encoding="utf-8")
    (repo / "examples.md").write_text(
        "WA_API_KEY='your-key'\n"
        "http://localhost:8000/v1\n"
        "https://user:secret@example.invalid/v1\n"
        "[link=https://example.invalid]workspace[/link]\n"
        "Traversal fixture: /etc/passwd\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    result = audit(repo, "--tracked", "--staged", "--history")
    assert result.returncode == 0, result.stdout
    assert "Privacy audit passed" in result.stdout


@pytest.mark.parametrize(
    ("prefix", "suffix", "rule"),
    [
        ("sk-", "z" * 44, "api-key-format"),
        ("ghp_", "a" * 36, "github-token-format"),
        ("gho_", "b" * 36, "github-token-format"),
        ("github_pat_", "c" * 60, "github-pat-format"),
        ("AKIA", "N" * 16, "aws-access-key-format"),
        ("-----BEGIN ", "PRIVATE KEY-----", "private-key-block"),
    ],
)
def test_key_formats_are_detected_without_printing_values(
    repo: Path, prefix: str, suffix: str, rule: str
) -> None:
    value = prefix + suffix
    (repo / "config.txt").write_text(value, encoding="utf-8")
    git(repo, "add", "config.txt")
    result = audit(repo, "--staged")
    assert result.returncode == 1
    assert f"staged/config.txt:{rule}" in result.stdout
    assert value not in result.stdout + result.stderr


def test_staged_contents_are_scanned_independently_of_worktree(repo: Path) -> None:
    value = "sk-" + "q" * 44
    target = repo / "config.txt"
    target.write_text(value, encoding="utf-8")
    git(repo, "add", "config.txt")
    target.write_text("The worktree is clean, but the index still has the key.", encoding="utf-8")
    assert audit(repo, "--tracked").returncode == 0
    staged = audit(repo, "--staged")
    assert staged.returncode == 1
    assert "staged/config.txt:api-key-format" in staged.stdout
    assert value not in staged.stdout


def test_removed_historical_secret_is_still_found(repo: Path) -> None:
    value = "ghp_" + "f" * 36
    (repo / "retired.txt").write_text(value, encoding="utf-8")
    git(repo, "add", "retired.txt")
    git(repo, "commit", "-m", "Synthetic credential fixture")
    git(repo, "rm", "retired.txt")
    git(repo, "commit", "-m", "Remove synthetic credential fixture")
    assert audit(repo).returncode == 0
    result = audit(repo, "--history")
    assert result.returncode == 1
    assert "/retired.txt:github-token-format" in result.stdout
    assert value not in result.stdout + result.stderr


@pytest.mark.parametrize("name", [".env", "private/notes.md", "data/cache.db", "runtime.log"])
def test_private_paths_fail_even_without_secret_content(repo: Path, name: str) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Harmless content; the path still needs review.", encoding="utf-8")
    git(repo, "add", name)
    result = audit(repo, "--staged")
    assert result.returncode == 1
    assert f"staged/{name}:private-" in result.stdout


def test_machine_paths_private_urls_and_password_literals_are_detected(repo: Path) -> None:
    content = "\n".join(
        [
            "/ho" + "me/private-user/project/file.md",
            "https://" + "192.168.42.7/v1",
            "pass" + "word = 'a-long-unknown-credential'",
        ]
    )
    (repo / "config.txt").write_text(content, encoding="utf-8")
    git(repo, "add", "config.txt")
    result = audit(repo)
    assert result.returncode == 1
    for rule in ("machine-absolute-path", "private-service-url", "credential-literal"):
        assert f"config.txt:{rule}" in result.stdout
    assert "private-user" not in result.stdout
    assert "192.168.42.7" not in result.stdout
    assert "a-long-unknown-credential" not in result.stdout


def test_untracked_candidates_are_opt_in_and_gitignored_state_is_excluded(repo: Path) -> None:
    (repo / ".gitignore").write_text(".agent/\n", encoding="utf-8")
    (repo / ".agent").mkdir()
    (repo / ".agent" / "runs.db").write_text("Local state", encoding="utf-8")
    (repo / "untracked.txt").write_text("sk-" + "u" * 44, encoding="utf-8")
    assert audit(repo).returncode == 0
    result = audit(repo, "--include-untracked")
    assert result.returncode == 1
    assert "untracked/untracked.txt:api-key-format" in result.stdout
    assert "runs.db" not in result.stdout


def test_worktree_symlink_parent_is_not_followed(repo: Path, tmp_path: Path) -> None:
    folder = repo / "notes"
    folder.mkdir()
    (folder / "public.md").write_text("Public note", encoding="utf-8")
    git(repo, "add", "notes/public.md")
    (folder / "public.md").unlink()
    folder.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "public.md").write_text("sk-" + "x" * 44, encoding="utf-8")
    folder.symlink_to(outside, target_is_directory=True)
    result = audit(repo, "--tracked")
    assert result.returncode == 1
    assert "tracked/notes/public.md:symlink-review-required" in result.stdout
    assert "api-key-format" not in result.stdout


def test_oversized_files_and_personal_history_email_require_review(repo: Path) -> None:
    (repo / "large.txt").write_bytes(b"x" * 2_000_001)
    git(repo, "add", "large.txt")
    result = audit(repo, "--staged")
    assert result.returncode == 1
    assert "large.txt:blob-size-limit" in result.stdout
    git(repo, "reset", "--", "large.txt")
    git(repo, "config", "user.email", "private-person@private.invalid")
    (repo / "README.md").write_text("Public update", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "Email review fixture")
    result = audit(repo, "--history")
    assert result.returncode == 1
    assert "personal-author-email" in result.stdout
    assert "private-person@private.invalid" not in result.stdout


def test_control_characters_in_filenames_are_escaped(repo: Path) -> None:
    (repo / "line\nname.txt").write_text("sk-" + "n" * 44, encoding="utf-8")
    git(repo, "add", ".")
    result = audit(repo, "--staged")
    assert result.returncode == 1
    assert "staged/line\\nname.txt:api-key-format" in result.stdout
    assert "staged/line\nname.txt" not in result.stdout
