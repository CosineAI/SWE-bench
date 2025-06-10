import os
import requests

def get_token_for_team(team_slug: str) -> str:
    """
    Fetch a GitHub token for the given team from the token provider API.

    Args:
        team_slug (str): Slug of the team

    Returns:
        str: Personal access token for the team

    Raises:
        Exception: If the token cannot be fetched or response is invalid
    """
    api_domain = os.getenv("TOKEN_API_DOMAIN", "http://localhost:3001")
    auth_header = os.getenv("TOKEN_AUTH_HEADER")
    if not auth_header:
        raise Exception("TOKEN_AUTH_HEADER env var must be set to fetch team tokens.")

    url = f"{api_domain}/github/token?team={team_slug}"
    headers = {"Authorization": auth_header}

    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch token for team '{team_slug}'. Status: {resp.status_code} Response: {resp.text}")

    data = resp.json()
    token = data.get("token")
    if not token:
        raise Exception(f"No 'token' field in response for team '{team_slug}'. Response: {data}")

    return token