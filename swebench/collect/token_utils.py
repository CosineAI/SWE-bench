import os
import requests
import threading

def get_tokens():
    """
    Fetch a list of GitHub tokens for the current team slugs from a local token service.

    - Reads TEAM_IDS (comma-separated team slug list) from env (required).
    - Reads GHTOKEN_SERVICE_DOMAIN (default http://localhost:3001).
    - Reads GHTOKEN_SERVICE_BEARER (token string) or falls back to SERVICE_AUTH.
    - For each slug, requests {domain}/github/token?team={slug} with Bearer <token>.
    - Returns a list of tokens (one per team).
    """
    team_ids = os.getenv("TEAM_IDS")
    if not team_ids:
        raise EnvironmentError(
            "TEAM_IDS environment variable not set. Please set TEAM_IDS to a comma-separated list of team slugs."
        )
    slugs = [slug.strip() for slug in team_ids.split(",") if slug.strip()]
    if not slugs:
        raise ValueError("No valid team slugs found in TEAM_IDS.")

    domain = os.getenv("GHTOKEN_SERVICE_DOMAIN", "http://localhost:3001")
    bearer = os.getenv("GHTOKEN_SERVICE_BEARER") or os.getenv("SERVICE_AUTH")
    if not bearer:
        raise EnvironmentError(
            "Missing GHTOKEN_SERVICE_BEARER or SERVICE_AUTH environment variable for token service authentication."
        )

    tokens = []
    headers = {"Authorization": f"Bearer {bearer}"}
    for slug in slugs:
        url = f"{domain.rstrip('/')}/github/token"
        try:
            resp = requests.get(url, headers=headers, params={"team": slug}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("token")
            if not token:
                raise ValueError(f"No 'token' field in response from {url} for team '{slug}'")
            tokens.append(token)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch token for team '{slug}' from {url}: {e}") from e
    return tokens


class TokenRotator:
    """
    Rotates through GitHub tokens associated with team slugs in TEAM_IDS.
    Fetches tokens on demand and caches them for the session.
    Thread-safe for concurrent use.
    """
    def __init__(self):
        team_ids = os.getenv("TEAM_IDS")
        if not team_ids:
            raise EnvironmentError(
                "TEAM_IDS environment variable not set. Please set TEAM_IDS to a comma-separated list of team slugs."
            )
        self.slugs = [slug.strip() for slug in team_ids.split(",") if slug.strip()]
        if not self.slugs:
            raise ValueError("No valid team slugs found in TEAM_IDS.")

        self.domain = os.getenv("GHTOKEN_SERVICE_DOMAIN", "http://localhost:3001")
        self.bearer = os.getenv("GHTOKEN_SERVICE_BEARER") or os.getenv("SERVICE_AUTH")
        if not self.bearer:
            raise EnvironmentError(
                "Missing GHTOKEN_SERVICE_BEARER or SERVICE_AUTH environment variable for token service authentication."
            )

        self.tokens_cache = {}  # slug -> token
        self.idx = 0
        self.lock = threading.Lock()

    def fetch_token(self, slug):
        """Fetch token for a single team slug from the token service."""
        url = f"{self.domain.rstrip('/')}/github/token"
        headers = {"Authorization": f"Bearer {self.bearer}"}
        resp = requests.get(url, headers=headers, params={"team": slug}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token")
        if not token:
            raise ValueError(f"No 'token' field in response from {url} for team '{slug}'")
        return token

    def current_token(self):
        """Return token for current index (fetch and cache if needed)."""
        with self.lock:
            slug = self.slugs[self.idx]
            if slug not in self.tokens_cache:
                self.tokens_cache[slug] = self.fetch_token(slug)
            return self.tokens_cache[slug]

    def next_token(self):
        """Advance to next slug, fetch token, and return it."""
        with self.lock:
            self.idx = (self.idx + 1) % len(self.slugs)
            slug = self.slugs[self.idx]
            if slug not in self.tokens_cache:
                self.tokens_cache[slug] = self.fetch_token(slug)
            return self.tokens_cache[slug]

    def num_tokens(self):
        return len(self.slugs)

# Expose a singleton TokenRotator for use elsewhere
token_rotator = TokenRotator()