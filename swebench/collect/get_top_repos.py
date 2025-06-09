#!/usr/bin/env python3

"""
Utility for fetching top-starred GitHub repositories by language.
"""

from typing import List
from ghapi.core import GhApi

__all__ = ["get_top_repos_by_language"]

def get_top_repos_by_language(
    language: str, max_repos: int, api: GhApi, pushed_after: str = None
) -> List[str]:
    """
    Fetch top-starred GitHub repositories for a given language, optionally filtering by recency.

    Args:
        language (str): The programming language to search for.
        max_repos (int): The maximum number of repositories to fetch.
        api (GhApi): An authenticated GhApi instance.
        pushed_after (str, optional): Only include repositories pushed after this date (YYYY-MM-DD). Defaults to None.

    Returns:
        List[str]: List of "owner/name" repo strings.
    """
    per_page = 100  # GitHub API max per page
    repos = []
    seen = set()
    page = 1
    print(
        f"Fetching top {max_repos} repositories for language: {language}"
        + (f" (pushed after {pushed_after})" if pushed_after else "")
    )

    # Build search query
    base_query = f"language:{language}"
    if pushed_after:
        base_query += f" pushed:>={pushed_after}"

    while len(repos) < max_repos:
        try:
            result = api.search.repos(
                q=base_query,
                sort="stars",
                order="desc",
                per_page=per_page,
                page=page,
            )
        except Exception as e:
            print(f"Error fetching page {page} for language {language}: {e}")
            break

        items = result.get("items", [])
        if not items:
            if page == 1:
                print(f"Warning: No repositories found for language '{language}'.")
            break

        added_this_page = 0
        for repo in items:
            full_name = repo.get("full_name")
            if full_name and full_name not in seen:
                repos.append(full_name)
                seen.add(full_name)
                added_this_page += 1
                if len(repos) >= max_repos:
                    break

        print(f"Fetched {len(repos)} / {max_repos} for {language} (page {page})")
        if added_this_page == 0:
            break  # No new repos, likely at the end
        page += 1

    if not repos:
        print(f"Warning: No repositories collected for language '{language}'.")
    else:
        print(f"Collected {len(repos)} repositories for language '{language}'.")
    return repos