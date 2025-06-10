import os
import requests
import threading

class GitHubTokenRotator:
    """
    Fetches and rotates GitHub Personal Access Tokens (PATs) from a local service.
    """

    def __init__(self, team_ids: list[str], domain: str = 'http://localhost:3001', auth_header: str | None = None):
        if not team_ids or not any(x.strip() for x in team_ids):
            raise ValueError("TEAM_IDS env var missing or empty: must supply at least one team slug.")
        self.team_ids = [x.strip() for x in team_ids if x.strip()]
        self.domain = domain.rstrip("/")
        self.auth_header = auth_header
        self._lock = threading.Lock()
        self._current_index = 0
        self._cached_token = None
        self._cached_team = None

    def _fetch_token(self, team_slug: str) -> str:
        url = f"{self.domain}/github/token?team={team_slug}"
        headers = {}
        if self.auth_header:
            headers["Authorization"] = self.auth_header
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch token for team '{team_slug}': {resp.status_code} {resp.text}")
        data = resp.json()
        if "token" not in data or not data["token"]:
            raise RuntimeError(f"Response missing 'token' for team '{team_slug}': {data}")
        return data["token"]

    def get_token(self) -> str:
        """
        Returns the currently cached token (fetches and caches on first call).
        """
        with self._lock:
            if self._cached_token is None:
                team = self.team_ids[self._current_index]
                self._cached_token = self._fetch_token(team)
                self._cached_team = team
            return self._cached_token

    def rotate_token(self) -> str:
        """
        Advance to the next team slug (cyclic), fetch & cache its token, return it.
        If rotated more times than len(team_ids) without reset, raises Exhausted exception.
        """
        with self._lock:
            self._current_index = (self._current_index + 1) % len(self.team_ids)
            team = self.team_ids[self._current_index]
            if self._cached_team == team:
                # Rotated through all teams, all tokens exhausted
                raise RuntimeError("All GitHub tokens exhausted: rotated through all TEAM_IDS. Reached rate limit on all tokens.")
            self._cached_token = self._fetch_token(team)
            self._cached_team = team
            return self._cached_token