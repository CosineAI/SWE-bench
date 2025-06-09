#!/usr/bin/env python3

"""
get_top_repos.py

Fetch the most-starred repositories for specified languages using the GitHub API.

Usage:
    python get_top_repos.py --languages python,javascript --per-language 100 --output repo_list.txt

Requires a GitHub token via GITHUB_TOKEN env variable or --token argument.
"""

import argparse
import os
import time
from ghapi.core import GhApi
from typing import List

def fetch_top_repos(api: GhApi, language: str, per_language: int) -> List[str]:
    """
    Fetch most-starred repos for a given language using the GitHub Search API.

    Args:
        api (GhApi): An authenticated GhApi instance.
        language (str): Programming language.
        per_language (int): Number of repos to fetch (max 1000).
    Returns:
        List[str]: List of "owner/name" repo strings.
    """
    repos = []
    per_page = 100
    for page in range(1, (per_language - 1) // per_page + 2):
        try:
            result = api.get(
                "search/repositories",
                q=f"language:{language}",
                sort="stars",
                order="desc",
                per_page=per_page,
                page=page,
            )
            items = result.get("items", [])
            for repo in items:
                repos.append(f"{repo['owner']['login']}/{repo['name']}")
            if len(repos) >= per_language or not items:
                break
            # Prevent hitting secondary rate limits
            time.sleep(0.5)
        except Exception as e:
            if "rate limit" in str(e).lower():
                print("Hit rate limit, sleeping for 60 seconds...")
                time.sleep(60)
                continue
            else:
                print(f"Error fetching repos for language {language}: {e}")
                break
    return repos[:per_language]


def main():
    parser = argparse.ArgumentParser(description="Fetch most-starred repos by language using the GitHub API.")
    parser.add_argument(
        "--languages",
        type=str,
        required=True,
        help="Comma-separated list of languages (e.g. python,javascript,ruby)",
    )
    parser.add_argument(
        "--per-language",
        type=int,
        default=100,
        help="Number of repos to fetch per language (max 1000)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output file (one repo per line, owner/name)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="GitHub token (or set GITHUB_TOKEN env var)",
    )
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GitHub token required (set GITHUB_TOKEN or use --token)")

    api = GhApi(token=token)

    all_repos = []
    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]
    for language in languages:
        print(f"Fetching top repos for language: {language}")
        repos = fetch_top_repos(api, language, args.per_language)
        for repo in repos:
            print(repo)
        all_repos.extend(repos)
        # Respect the API limit for searches (30/minute for authenticated)
        time.sleep(2)

    with open(args.output, "w") as f:
        for repo in all_repos:
            f.write(repo + "\n")

    print(f"\nWrote {len(all_repos)} repos to {args.output}")


if __name__ == "__main__":
    main()