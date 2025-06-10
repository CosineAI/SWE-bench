import os
import requests

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