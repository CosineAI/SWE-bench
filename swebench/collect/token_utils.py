import os
import requests
import threading
from dotenv import load_dotenv

load_dotenv()

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
    Supports invalidating tokens (e.g., on 401 error) so they are not reused.
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
        self.invalid_slugs = set()

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

    def _slug_from_token(self, token_str):
        """Find the slug corresponding to a particular token string."""
        with self.lock:
            for slug, tok in self.tokens_cache.items():
                if tok == token_str:
                    return slug
        return None

    def invalidate_token(self, token_str):
        """
        Invalidate the token (by token string), marking its slug as invalid.
        That slug will be skipped when rotating tokens.
        """
        with self.lock:
            slug = self._slug_from_token(token_str)
            if slug is not None:
                self.invalid_slugs.add(slug)
                # Optionally remove from cache (not strictly necessary, but keeps things tidy)
                if slug in self.tokens_cache:
                    del self.tokens_cache[slug]

    def _find_next_valid_idx(self, start_idx=None):
        """Helper to get the index of the next valid slug, or None if all are invalid."""
        n = len(self.slugs)
        if n == 0:
            return None
        idx = self.idx if start_idx is None else start_idx
        tried = 0
        while tried < n:
            slug = self.slugs[idx]
            if slug not in self.invalid_slugs:
                return idx
            idx = (idx + 1) % n
            tried += 1
        return None  # all invalid

    def current_token(self):
        """
        Return token for current index (fetch and cache if needed).
        Skips invalidated slugs; raises RuntimeError if all tokens are invalid.
        """
        with self.lock:
            idx = self._find_next_valid_idx()
            if idx is None:
                raise RuntimeError("All tokens have been invalidated; no valid tokens remain.")
            self.idx = idx
            slug = self.slugs[self.idx]
            if slug not in self.tokens_cache:
                self.tokens_cache[slug] = self.fetch_token(slug)
            return self.tokens_cache[slug]

    def next_token(self):
        """
        Advance to next valid slug, fetch token, and return it.
        Skips invalidated slugs; raises RuntimeError if all tokens are invalid.
        """
        with self.lock:
            n = len(self.slugs)
            if n == 0:
                raise RuntimeError("No slugs configured in TokenRotator.")
            start_idx = (self.idx + 1) % n
            idx = self._find_next_valid_idx(start_idx=start_idx)
            if idx is None:
                raise RuntimeError("All tokens have been invalidated; no valid tokens remain.")
            self.idx = idx
            slug = self.slugs[self.idx]
            if slug not in self.tokens_cache:
                self.tokens_cache[slug] = self.fetch_token(slug)
            return self.tokens_cache[slug]

    def num_tokens(self):
        """Return number of valid (not invalidated) tokens remaining."""
        with self.lock:
            return len([slug for slug in self.slugs if slug not in self.invalid_slugs])

# Expose a singleton TokenRotator for use elsewhere
token_rotator = TokenRotator()