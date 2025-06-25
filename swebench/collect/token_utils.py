import os
import requests
import threading
import logging
from dotenv import load_dotenv

logger = logging.getLogger("swebench.collect.token_utils")

load_dotenv()

def get_tokens():
    """
    Get GitHub tokens from environment variables or token service.
    
    Tries to get tokens in this order:
    1. From GITHUB_TOKENS environment variable (comma-separated)
    2. From GITHUB_TOKEN environment variable
    3. From token service (if TEAM_IDS and GHTOKEN_SERVICE_BEARER are set)
    
    Returns:
        List[str]: List of GitHub tokens
    """
    logger.info("Starting token fetch process...")
    
    # Try to get tokens from GITHUB_TOKENS
    github_tokens = os.getenv("GITHUB_TOKENS")
    if github_tokens:
        logger.info(f"Found GITHUB_TOKENS environment variable")
        tokens = [token.strip() for token in github_tokens.split(",") if token.strip()]
        if tokens:
            logger.info(f"Found {len(tokens)} token(s) in GITHUB_TOKENS")
            return tokens
        logger.warning("GITHUB_TOKENS is set but no valid tokens found")
    
    # Try to get token from GITHUB_TOKEN
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        return [github_token]
    
    # Fall back to token service if configured
    team_ids = os.getenv("TEAM_IDS")
    if team_ids:
        logger.info(f"Using token service to fetch GitHub tokens for teams: {team_ids}")
        domain = os.getenv("GHTOKEN_SERVICE_DOMAIN", "http://localhost:3001")
        bearer = os.getenv("GHTOKEN_SERVICE_BEARER") or os.getenv("SERVICE_AUTH")
        if not bearer:
            raise EnvironmentError(
                "Missing GHTOKEN_SERVICE_BEARER or SERVICE_AUTH environment variable for token service authentication."
            )

        slugs = [slug.strip() for slug in team_ids.split(",") if slug.strip()]
        if not slugs:
            raise ValueError("No valid team slugs found in TEAM_IDS.")

        tokens = []
        headers = {"Authorization": f"Bearer {bearer}"}
        for slug in slugs:
            url = f"{domain.rstrip('/')}/github/token"
            try:
                logger.debug(f"Fetching token for team: {slug}")
                resp = requests.get(url, headers=headers, params={"team": slug}, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                token = data.get("token")
                if not token:
                    logger.error(f"No 'token' field in response from {url} for team '{slug}'")
                    continue
                logger.debug(f"Successfully fetched token for team: {slug}")
                tokens.append(token)
            except Exception as e:
                logger.error(f"Failed to fetch token for team '{slug}' from {url}: {e}")
        
        if not tokens:
            raise EnvironmentError("Failed to fetch any tokens from the token service")
            
        logger.info(f"Successfully fetched {len(tokens)} tokens from {len(slugs)} team(s)")
        return tokens
    
    # No tokens found
    raise EnvironmentError(
        "No GitHub tokens found. Please set GITHUB_TOKEN, GITHUB_TOKENS, or configure TEAM_IDS with token service."
    )


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

# Expose a singleton TokenRotator for use elsewhere
token_rotator = TokenRotator()

# Alias for backward compatibility
get_github_token = get_tokens
