#!/usr/bin/env python3

"""Script to collect pull requests and convert them to candidate task instances"""

import argparse
import os
import traceback
import sys

from dotenv import load_dotenv
from multiprocessing import Pool
import os
import re
from swebench.collect.build_dataset import main as build_dataset
from swebench.collect.print_pulls import main as print_pulls
from swebench.collect.get_top_repos import get_top_repos_by_language
from ghapi.core import GhApi
from swebench.collect.token_utils import get_tokens

load_dotenv()


def read_repos_from_markdown(file_path: str) -> list:
    """Extract GitHub repository URLs from a markdown file.
    
    This function parses a markdown file and extracts all GitHub repository URLs
    in the format 'owner/repo'. It handles both plain URLs and markdown links.
    
    Args:
        file_path: Path to the markdown file containing GitHub repository URLs
        
    Returns:
        list: Unique list of repository identifiers in 'owner/repo' format
        
    Example:
        Input file content:
            - https://github.com/owner1/repo1
            - [https://github.com/owner2/repo2](https://github.com/owner2/repo2)
        
        Returns:
            ['owner1/repo1', 'owner2/repo2']
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all GitHub repository URLs in the format github.com/owner/repo
    urls = re.findall(r'https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)', content)
    
    # Clean up the repository names (remove any trailing slashes or other characters)
    repos = [url.rstrip('/') for url in urls]
    
    # Remove duplicates while preserving order
    seen = set()
    return [repo for repo in repos if not (repo in seen or seen.add(repo))]


def get_github_token():
    """Get GitHub tokens from both direct token and token service.
    
    Returns:
        list: List of GitHub tokens, with direct token (if available) included in the rotation
        
    Raises:
        EnvironmentError: If no valid tokens are found
    """
    tokens = []
    
    # Add direct token if available
    direct_token = os.getenv("GITHUB_TOKEN")
    if direct_token:
        tokens.append(direct_token.strip())
    
    # Add tokens from token service if available
    try:
        service_tokens = get_tokens()
        tokens.extend(service_tokens)
    except Exception as e:
        if not direct_token:
            # Only raise if we don't have a direct token either
            raise EnvironmentError(
                "Failed to get GitHub tokens. Either set GITHUB_TOKEN environment variable "
                "or configure token service with TEAM_IDS and SERVICE_AUTH."
            ) from e
    
    if not tokens:
        raise EnvironmentError(
            "No GitHub tokens found. Set GITHUB_TOKEN or configure token service."
        )
        
    return tokens


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


def process_repository_file(repo_file):
    """Process a repository file and return the list of repositories."""
    try:
        repos = read_repos_from_markdown(repo_file)
        if not repos:
            print(f"No valid repositories found in {repo_file}", file=sys.stderr)
            return None
        print(f"Read {len(repos)} repositories from {repo_file}")
        return repos
    except Exception as e:
        print(f"Error reading repository file: {e}", file=sys.stderr)
        return None


def main(
    repos: list = None,
    path_prs: str = None,
    path_tasks: str = None,
    max_pulls: int = None,
    cutoff_date: str = None,
    languages: list = None,
    max_repos_per_language: int = 50,
    repo_file: str = None,
    recency_months: int = None,
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
    # Convert paths to absolute paths and create directories if they don't exist
    if path_prs:
        path_prs_abs = os.path.abspath(path_prs)
        os.makedirs(path_prs_abs, exist_ok=True)
    else:
        path_prs_abs = None
        
    if path_tasks:
        path_tasks_abs = os.path.abspath(path_tasks)
        os.makedirs(path_tasks_abs, exist_ok=True)
    else:
        path_tasks_abs = None

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
        tokens = get_github_token()
        if not tokens:
            raise Exception(
                "No GitHub tokens found. Set GITHUB_TOKEN or configure token service with TEAM_IDS and SERVICE_AUTH."
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

    tokens = get_github_token()
    if not tokens:
        raise Exception(
            "No GitHub tokens found. Set GITHUB_TOKEN or configure token service with TEAM_IDS and SERVICE_AUTH."
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
    
    # Create mutually exclusive group for repo source
    repo_group = parser.add_mutually_exclusive_group(required=True)
    repo_group.add_argument(
        "--repos",
        nargs="+",
        help="List of repositories (e.g., `sqlfluff/sqlfluff`) to create task instances for",
    )
    repo_group.add_argument(
        "--languages",
        nargs="+",
        help="Programming language(s) to fetch top GitHub repos for (e.g., --languages python javascript go)",
    )
    repo_group.add_argument(
        "--repo-file",
        type=str,
        help="Path to markdown file containing a list of GitHub repository URLs",
    )
    
    # Add other arguments
    parser.add_argument(
        "--max_repos_per_language",
        type=int,
        help="Max repos to fetch for each language (default: 50)",
        default=50,
    )
    # Set default paths relative to the script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_prs = os.path.join(script_dir, "../../data/prs")
    default_tasks = os.path.join(script_dir, "../../data/tasks")
    
    parser.add_argument(
        "--path_prs", 
        type=str, 
        default=default_prs,
        help=f"Path to folder to save PR data files to (default: {default_prs})"
    )
    parser.add_argument(
        "--path_tasks",
        type=str,
        default=default_tasks,
        help=f"Path to folder to save task instance data files to (default: {default_tasks})",
    )
    parser.add_argument(
        "--max_pulls", 
        type=int, 
        help="Maximum number of pulls to log per repository", 
        default=100
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
    
    # Process repository file if provided
    if args.repo_file:
        args.repos = process_repository_file(args.repo_file)
        if not args.repos:
            print("No valid repositories to process. Exiting.", file=sys.stderr)
            sys.exit(1)
    
    # Calculate cutoff date from recency_months if provided
    if args.recency_months is not None and args.recency_months > 0:
        from datetime import datetime, timedelta
        args.cutoff_date = (datetime.now() - timedelta(days=args.recency_months*30)).strftime("%Y%m%d")
        print(f"Using cutoff date: {args.cutoff_date} (last {args.recency_months} months)")
    elif args.cutoff_date:
        print(f"Using provided cutoff date: {args.cutoff_date}")
    else:
        print("No cutoff date specified, will fetch all available PRs")

    # Call the main function with processed arguments
    try:
        main(
            repos=args.repos,
            path_prs=args.path_prs,
            path_tasks=args.path_tasks,
            max_pulls=args.max_pulls,
            cutoff_date=args.cutoff_date,
            languages=args.languages,
            max_repos_per_language=args.max_repos_per_language,
            repo_file=args.repo_file,
            recency_months=args.recency_months
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
