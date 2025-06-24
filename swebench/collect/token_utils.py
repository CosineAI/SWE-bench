import os
import requests
import threading
import logging
from dotenv import load_dotenv

logger = logging.getLogger("swebench.collect.token_utils")

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
        logger.info(f"Fetched new token for slug '{slug}'")
        return token

    def current_token(self):
        """Return token for current index (fetch and cache if needed)."""
        with self.lock:
            slug = self.slugs[self.idx]
            if slug not in self.tokens_cache:
                self.tokens_cache[slug] = self.fetch_token(slug)
            return self.tokens_cache[slug]

    def next_token(self):
        """Advance to next slug, fetch token, and return it. Raises if no tokens remain."""
        with self.lock:
            if not self.slugs:
                raise RuntimeError("No tokens left in TokenRotator.")
            prev_idx = self.idx
            self.idx = (self.idx + 1) % len(self.slugs)
            slug = self.slugs[self.idx]
            if self.idx != prev_idx:
                logger.debug(f"Switched to slug '{slug}' (idx {self.idx})")
            if slug not in self.tokens_cache:
                self.tokens_cache[slug] = self.fetch_token(slug)
            return self.tokens_cache[slug]

    def refresh_current_token(self):
        """
        Refresh the token for the current slug (fetch a new token and update the cache).
        Returns the refreshed token.
        """
        with self.lock:
            if not self.slugs:
                raise RuntimeError("No team slugs available to refresh token.")
            slug = self.slugs[self.idx]
            self.tokens_cache[slug] = self.fetch_token(slug)
            logger.info(f"Refreshed token for slug '{slug}'.")
            return self.tokens_cache[slug]

    def invalidate_current_token(self, slug=None):
        """
        Remove the current slug (and its token) from rotation due to 401/invalidity.
        Accepts an optional slug param for explicit invalidation (defaults to current).
        Adjust idx as needed.
        """
        with self.lock:
            if not self.slugs:
                return
            if slug is not None and slug in self.slugs:
                idx = self.slugs.index(slug)
            else:
                idx = self.idx
            slug_to_remove = self.slugs[idx]
            self.tokens_cache.pop(slug_to_remove, None)
            self.slugs.pop(idx)
            logger.warning(f"Invalidated token for slug '{slug_to_remove}', tokens left: {len(self.slugs)}")
            # Adjust idx if needed
            if self.idx >= len(self.slugs):
                self.idx = 0

    def num_tokens(self):
        with self.lock:
            return len(self.slugs)

def get_github_token():
    """
    Get all available GitHub tokens from multiple sources in this order:
    1. GITHUB_TOKENS (comma-separated list)
    2. GITHUB_TOKEN (single token)
    3. Token service (via get_tokens() if TEAM_IDS is set)
    
    Returns:
        list: List of unique GitHub tokens
    """
    tokens = []
    seen = set()
    
    # Add tokens from GITHUB_TOKENS if available
    if tokens_env := os.getenv("GITHUB_TOKENS"):
        new_tokens = [t.strip() for t in tokens_env.split(",") if t.strip()]
        tokens.extend(new_tokens)
        seen.update(new_tokens)
    
    # Add direct token if available and not already in the list
    if direct_token := os.getenv("GITHUB_TOKEN"):
        direct_token = direct_token.strip()
        if direct_token and direct_token not in seen:
            tokens.append(direct_token)
            seen.add(direct_token)
    
    # Add tokens from token service if TEAM_IDS is set
    if os.getenv("TEAM_IDS"):
        try:
            service_tokens = [t for t in get_tokens() if t not in seen]
            tokens.extend(service_tokens)
            seen.update(service_tokens)
        except Exception as e:
            logger.warning(f"Could not get tokens from token service: {e}")
    
    if not tokens:
        raise EnvironmentError(
            "No GitHub tokens found. Set GITHUB_TOKENS, GITHUB_TOKEN, or configure token service with TEAM_IDS and SERVICE_AUTH."
        )
    
    return tokens

# Expose a singleton TokenRotator for use elsewhere
token_rotator = TokenRotator()