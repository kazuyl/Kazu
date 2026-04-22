from __future__ import annotations

import base64
import json
import os
from typing import Any, Optional

import requests


class GitHubStore:
    def __init__(self) -> None:
        self.token = os.environ["GITHUB_TOKEN"]
        self.owner = os.environ["GITHUB_OWNER"]
        self.repo = os.environ["GITHUB_REPO"]
        self.branch = os.environ.get("GITHUB_BRANCH", "main")
        self.base_path = os.environ.get("GITHUB_DASHBOARD_DIR", "docs")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _url(self, path: str) -> str:
        rel = f"{self.base_path.strip('/')}/{path.lstrip('/')}"
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/contents/{rel}"

    def read_json(self, path: str, default: Any) -> Any:
        resp = self.session.get(self._url(path), params={"ref": self.branch}, timeout=30)
        if resp.status_code == 404:
            return default
        resp.raise_for_status()
        data = resp.json()
        content = base64.b64decode(data["content"])
        return json.loads(content.decode("utf-8"))

    def get_sha(self, path: str) -> Optional[str]:
        resp = self.session.get(self._url(path), params={"ref": self.branch}, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("sha")

    def write_json(self, path: str, payload: Any, message: str) -> None:
        raw = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        body = {
            "message": message,
            "content": encoded,
            "branch": self.branch,
        }
        sha = self.get_sha(path)
        if sha:
            body["sha"] = sha
        resp = self.session.put(self._url(path), json=body, timeout=30)
        resp.raise_for_status()
