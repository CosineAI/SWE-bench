#!/usr/bin/env python3

"""Script to collect pull requests and convert them to candidate task instances"""

import argparse
import os
import traceback

from dotenv import load_dotenv
from multiprocessing import Pool
from swebench.collect.build_dataset import main as build_dataset
from swebench.collect.print_pulls import main as print_pulls
from swebench.collect.get_top_repos import get_top_repos_by_language
from ghapi.core import GhApi
from swebench.collect.token_utils import get_tokens

load_dotenv()


def split_instances(input_list: list, n: int) -> list:
    """
    Split a list into n approximately equal length sublists

    Args:
        input_list (list): List to split
        n (int): Number of sublists to split into
    Returns:
        result (list): List of sublists
    """
    avg_length = len(input_list) // n
    remainder = len(input_list) % n
    result, start = [], 0

    for i in range(n):
        length = avg_length + 1 if i < remainder else avg_length
        sublist = input_list[start : start + length]
        result.append(sublist)
        start += length

    return result


def construct_data_files(data: dict):
    """
    Logic for combining multiple .all PR files into a single fine tuning dataset

    Args:
        data (dict): Dictionary containing the following keys:
            repos (list): List of repositories to retrieve instruction data for
            path_prs (str): Path to save PR data files to
            path_tasks (str): Path to save task instance data files to
            token (str): GitHub token to use for API requests
    """
    repos, path_prs, path_tasks, max_pulls, cutoff_date, token = (
        data["repos"],
        data["path_prs"],
        data["path_tasks"],
        data["max_pulls"],
        data["cutoff_date"],
        data["token"],
    )
    for repo in repos:
        repo = repo.strip(",").strip()
        repo_name = repo.split("/")[1]
        try:
            path_pr = os.path.join(path_prs, f"{repo_name}-prs.jsonl")
            if cutoff_date:
                path_pr = path_pr.replace(".jsonl", f"-{cutoff_date}.jsonl")
            if not os.path.exists(path_pr):
                print(f"Pull request data for {repo} not found, creating...")
                print_pulls(
                    repo, path_pr, token, max_pulls=max_pulls, cutoff_date=cutoff_date
                )
                print(f"✅ Successfully saved PR data for {repo} to {path_pr}")
            else:
                print(
                    f"📁 Pull request data for {repo} already exists at {path_pr}, skipping..."
                )

            path_task = os.path.join(path_tasks, f"{repo_name}-task-instances.jsonl")
            if not os.path.exists(path_task):
                print(f"Task instance data for {repo} not found, creating...")
                build_dataset(path_pr, path_task, token)
                print(
                    f"✅ Successfully saved task instance data for {repo} to {path_task}"
                )
            else:
                print(
                    f"📁 Task instance data for {repo} already exists at {path_task}, skipping..."
                )
        except Exception as e:
            print("-" * 80)
            print(f"Something went wrong for {repo}, skipping: {e}")
            print("Here is the full traceback:")
            traceback.print_exc()
            print("-" * 80)


def main(
    repos: list = None,
    path_prs: str = None,
    path_tasks: str = None,
    max_pulls: int = None,
    cutoff_date: str = None,
    languages: list = None,
    max_repos_per_language: int = 50,
):
    """
    Spawns multiple threads given multiple GitHub tokens for collecting fine tuning data

    Args:
        repos (list): List of repositories to retrieve instruction data for
        path_prs (str): Path to save PR data files to
        path_tasks (str): Path to save task instance data files to
        cutoff_date (str): Cutoff date for PRs to consider in format YYYYMMDD
        languages (list): List of language names (optional)
        max_repos_per_language (int): Max repos to collect per language (optional)
    """
    # Gather repos via languages if necessary
    all_repos = set()
    # Handle explicit repos from CLI
    if repos:
        # Accept comma-separated string or list
        if isinstance(repos, str):
            repos = [r.strip() for r in repos.split(",")]
        for repo in repos:
            if repo:
                all_repos.add(repo.strip(",").strip())

    # Handle language-based repo fetching
    if languages:
        # Accept comma-separated string or list
        if isinstance(languages, str):
            languages = [l.strip() for l in languages.split(",")]  # noqa: E741
        # Get GitHub tokens for GhApi (use first token)
        tokens = get_tokens()
        if not tokens:
            raise Exception(
                "No GitHub tokens returned from token service. Check TEAM_IDS and token service configuration."
            )
        gh_token = tokens[0].strip()
        api = GhApi(token=gh_token)
        for lang in languages:
            try:
                top_repos = get_top_repos_by_language(lang, max_repos_per_language, api)
                for repo in top_repos:
                    all_repos.add(repo)
            except Exception as e:
                print(f"Error getting repos for language '{lang}': {e}")

    if not all_repos:
        raise Exception(
            "No repositories provided or discovered. Use --repos and/or --languages."
        )

    all_repos = sorted(all_repos)
    print(f"Summary: {len(all_repos)} total repositories selected for processing.")
    if languages:
        print("Languages used: ", ", ".join(languages))
    print("Repositories:")
    for repo in all_repos:
        print(f" - {repo}")

    path_prs_abs, path_tasks_abs = os.path.abspath(path_prs), os.path.abspath(path_tasks)
    print(f"Will save PR data to {path_prs_abs}")
    print(f"Will save task instance data to {path_tasks_abs}")

    tokens = get_tokens()
    if not tokens:
        raise Exception(
            "No GitHub tokens returned from token service. Check TEAM_IDS and token service configuration."
        )
    data_task_lists = split_instances(all_repos, len(tokens))

    data_pooled = [
        {
            "repos": repos,
            "path_prs": path_prs_abs,
            "path_tasks": path_tasks_abs,
            "max_pulls": max_pulls,
            "cutoff_date": cutoff_date,
            "token": token,
        }
        for repos, token in zip(data_task_lists, tokens)
    ]

    with Pool(len(tokens)) as p:
        p.map(construct_data_files, data_pooled)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repos",
        nargs="+",
        help="List of repositories (e.g., `sqlfluff/sqlfluff`) to create task instances for",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        help="Programming language(s) to fetch top GitHub repos for (e.g., --languages python javascript go)",
        default=None,
    )
    parser.add_argument(
        "--max_repos_per_language",
        type=int,
        help="Max repos to fetch for each language (default: 50)",
        default=50,
    )
    parser.add_argument(
        "--path_prs", type=str, help="Path to folder to save PR data files to"
    )
    parser.add_argument(
        "--path_tasks",
        type=str,
        help="Path to folder to save task instance data files to",
    )
    parser.add_argument(
        "--max_pulls", type=int, help="Maximum number of pulls to log", default=None
    )
    parser.add_argument(
        "--cutoff_date",
        type=str,
        help="Cutoff date for PRs to consider in format YYYYMMDD",
        default=None,
    )
    parser.add_argument(
        "--recency_months", "--months",
        type=int,
        default=None,
        help="(Optional) Only include repositories pushed within the last N months (approximate, 30*N days).",
    )
    args = parser.parse_args()

    # Calculate repo cutoff if recency_months is set
    repo_cutoff_date = None
    if args.recency_months is not None:
        from datetime import datetime, timedelta
        repo_cutoff_date = (datetime.utcnow() - timedelta(days=30 * args.recency_months)).strftime("%Y-%m-%d")

    # Patch main call to pass the cutoff to language-based repo discovery
    def main_with_recency(
        repos: list = None,
        path_prs: str = None,
        path_tasks: str = None,
        max_pulls: int = None,
        cutoff_date: str = None,
        languages: list = None,
        max_repos_per_language: int = 50,
    ):
        all_repos = set()
        if repos:
            if isinstance(repos, str):
                repos = [r.strip() for r in repos.split(",")]
            for repo in repos:
                if repo:
                    all_repos.add(repo.strip(",").strip())

        if languages:
            if isinstance(languages, str):
                languages = [l.strip() for l in languages.split(",")]  # noqa: E741
            tokens = get_tokens()
            if not tokens:
                raise Exception(
                    "No GitHub tokens returned from token service. Check TEAM_IDS and token service configuration."
                )
            gh_token = tokens[0].strip()
            api = GhApi(token=gh_token)
            for lang in languages:
                try:
                    # Pass repo_cutoff_date as pushed_after if set
                    from swebench.collect.get_top_repos import get_top_repos_by_language
                    top_repos = get_top_repos_by_language(
                        lang, max_repos_per_language, api, pushed_after=repo_cutoff_date
                    )
                    for repo in top_repos:
                        all_repos.add(repo)
                except Exception as e:
                    print(f"Error getting repos for language '{lang}': {e}")

        if not all_repos:
            raise Exception(
                "No repositories provided or discovered. Use --repos and/or --languages."
            )

        all_repos_sorted = sorted(all_repos)
        print(f"Summary: {len(all_repos_sorted)} total repositories selected for processing.")
        if languages:
            print("Languages used: ", ", ".join(languages))
        print("Repositories:")
        for repo in all_repos_sorted:
            print(f" - {repo}")

        path_prs_abs, path_tasks_abs = os.path.abspath(path_prs), os.path.abspath(path_tasks)
        print(f"Will save PR data to {path_prs_abs}")
        print(f"Will save task instance data to {path_tasks_abs}")

        tokens = get_tokens()
        if not tokens:
            raise Exception(
                "No GitHub tokens returned from token service. Check TEAM_IDS and token service configuration."
            )
        data_task_lists = split_instances(all_repos_sorted, len(tokens))

        data_pooled = [
            {
                "repos": repos,
                "path_prs": path_prs_abs,
                "path_tasks": path_tasks_abs,
                "max_pulls": max_pulls,
                "cutoff_date": cutoff_date,
                "token": token,
            }
            for repos, token in zip(data_task_lists, tokens)
        ]

        from multiprocessing import Pool
        with Pool(len(tokens)) as p:
            p.map(construct_data_files, data_pooled)

    # Replace call to main with enhanced version
    main_with_recency(
        repos=args.repos,
        path_prs=args.path_prs,
        path_tasks=args.path_tasks,
        max_pulls=args.max_pulls,
        cutoff_date=args.cutoff_date,
        languages=args.languages,
        max_repos_per_language=args.max_repos_per_language,
    )
