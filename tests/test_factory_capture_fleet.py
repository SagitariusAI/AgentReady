from __future__ import annotations

import json
from pathlib import Path

from factory_capture.fleet import deploy_fleet, fleet_status


def _write_project(home: Path, project_id: str, root: Path, *, status: str = "active") -> None:
    path = home / "data" / "project-registry" / "projects" / f"{project_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": project_id,
                "name": project_id.title(),
                "status": status,
                "topology_root_key": "repo",
                "paths": {"repo": str(root)},
            }
        ),
        encoding="utf-8",
    )


def _fake_git_repo(path: Path) -> None:
    (path / ".git" / "hooks").mkdir(parents=True)


def test_fleet_deploy_initializes_and_hooks_registered_git_repos(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    _fake_git_repo(repo_a)
    _fake_git_repo(repo_b)
    _write_project(tmp_path, "repo-a", repo_a)
    _write_project(tmp_path, "repo-b", repo_b)

    assert fleet_status(tmp_path)["status"] == "FAIL"
    deployed = deploy_fleet(tmp_path)

    assert deployed["status"] == "PASS"
    assert deployed["summary"]["eligible_git_repos"] == 2
    assert deployed["summary"]["initialized_repos"] == 2
    assert deployed["summary"]["fully_hooked_repos"] == 2
    assert deployed["summary"]["captured_events"] == 2
    assert all((repo / ".factory_capture" / "config.json").exists() for repo in (repo_a, repo_b))
    assert all((repo / ".git" / "hooks" / "post-commit").exists() for repo in (repo_a, repo_b))
    for repo in (repo_a, repo_b):
        exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        assert "/.factory_capture/" in exclude.splitlines()
        hook = (repo / ".git" / "hooks" / "post-commit").read_text(encoding="utf-8")
        assert str(tmp_path / "src").replace("\\", "/") in hook


def test_fleet_deploy_is_idempotent_and_reports_non_git_projects(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    vault = tmp_path / "vault"
    _fake_git_repo(repo)
    vault.mkdir()
    _write_project(tmp_path, "repo", repo)
    _write_project(tmp_path, "vault", vault)

    first = deploy_fleet(tmp_path)
    second = deploy_fleet(tmp_path)

    assert first["status"] == second["status"] == "PASS"
    assert second["summary"]["captured_events"] == 1
    assert second["summary"]["non_git_projects"] == 1
    exclude = repo / ".git" / "info" / "exclude"
    assert exclude.read_text(encoding="utf-8").splitlines().count("/.factory_capture/") == 1
    assert (tmp_path / "reports" / "factory-capture-fleet" / "latest.json").exists()
