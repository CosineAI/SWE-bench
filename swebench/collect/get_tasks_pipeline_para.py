#!/usr/bin/env python3

"""Parallelized script to collect pull requests and convert them to candidate task instances
using multiple GitHub tokens for higher throughput."""

import argparse
import os
import sys
import traceback
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from ghapi.core import GhApi

# Local imports
from swebench.collect.build_dataset import main as build_dataset
from swebench.collect.print_pulls import main as print_pulls
from swebench.collect.get_top_repos import get_top_repos_by_language
from swebench.collect.token_utils import get_github_token

load_dotenv()

class TokenManager:
    """Manages GitHub tokens with rate limiting and consumption tracking."""
    
    def __init__(self, tokens: List[str]):
        self.tokens = tokens.copy()
        self.token_usage = {token: 0 for token in tokens}
        self.token_lock = threading.Lock()
        self.current_index = 0
        print(f"TokenManager initialized with {len(self.tokens)} tokens")
        
    def get_token(self) -> str:
        """Get the next available token in round-robin fashion."""
        with self.token_lock:
            token = self.tokens[self.current_index % len(self.tokens)]
            self.token_usage[token] += 1
            self.current_index += 1
            print(f"Using token {token[:8]}... (usage: {self.token_usage[token]})")
            return token
    
    def get_usage_stats(self) -> Dict[str, int]:
        """Get usage statistics for all tokens."""
        return self.token_usage.copy()

class ParallelTaskProcessor:
    def __init__(self, token_manager: TokenManager, max_workers: int = 10):
        """Initialize with token manager and worker count.
        
        Args:
            token_manager: TokenManager instance for handling tokens
            max_workers: Maximum number of concurrent workers per token
        """
        self.token_manager = token_manager
        self.max_workers = max_workers
        
    def process_repository(self, repo: str, path_prs: str, path_tasks: str, 
                          max_pulls: Optional[int] = None, 
                          cutoff_date: Optional[str] = None) -> Dict[str, Any]:
        """Process a single repository to collect PRs and generate tasks."""
        token = self.token_manager.get_token()
        repo_name = repo.split("/")[1] if "/" in repo else repo
        result = {"repo": repo, "success": False, "error": None}
        
        try:
            # Process PRs
            path_pr = os.path.join(path_prs, f"{repo_name}-prs.jsonl")
            if cutoff_date:
                path_pr = str(Path(path_pr).with_name(f"{Path(path_pr).stem}-{cutoff_date}{Path(path_pr).suffix}"))
            
            if not os.path.exists(path_pr):
                print(f"[Token {token[:8]}...] Processing PRs for {repo}")
                print_pulls(repo, path_pr, token, max_pulls=max_pulls, cutoff_date=cutoff_date)
            
            # Generate task instances
            path_task = os.path.join(path_tasks, f"{repo_name}-task-instances.jsonl")
            if not os.path.exists(path_task):
                print(f"[Token {token[:8]}...] Generating tasks for {repo}")
                build_dataset(path_pr, path_task, token)
            
            result["success"] = True
            
        except Exception as e:
            result["error"] = str(e)
            print(f"[ERROR] Failed to process {repo}: {e}")
            traceback.print_exc()
            
        return result

def read_repos_from_markdown(file_path: str) -> List[str]:
    """Extract GitHub repository URLs from a markdown file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all GitHub repository URLs
    urls = re.findall(r'https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)', content)
    
    # Clean up and deduplicate
    repos = [url.rstrip('/') for url in urls]
    seen = set()
    return [repo for repo in repos if not (repo in seen or seen.add(repo))]

def main(
    repos: List[str] = None,
    path_prs: str = None,
    path_tasks: str = None,
    max_pulls: int = 100,
    cutoff_date: str = None,
    languages: List[str] = None,
    max_repos_per_language: int = 50,
    repo_file: str = None,
    recency_months: int = None,
    max_workers: int = 10
):
    """Main function to process repositories in parallel using multiple tokens."""
    # Create output directories
    path_prs_abs = os.path.abspath(path_prs) if path_prs else None
    path_tasks_abs = os.path.abspath(path_tasks) if path_tasks else None
    
    for path in [path_prs_abs, path_tasks_abs]:
        if path:
            os.makedirs(path, exist_ok=True)
    
    # Get all repositories to process
    all_repos = set()
    
    # Add explicit repositories
    if repos:
        all_repos.update(r.strip() for r in repos if r.strip())
    
    # Add repositories from file if provided
    if repo_file:
        try:
            file_repos = read_repos_from_markdown(repo_file)
            all_repos.update(file_repos)
        except Exception as e:
            print(f"Error reading repository file: {e}", file=sys.stderr)
    
    # Add repositories by language
    if languages:
        tokens = get_github_token()
        if tokens:
            api = GhApi(token=tokens[0])
            for lang in languages:
                try:
                    lang_repos = get_top_repos_by_language(lang, max_repos_per_language, api)
                    all_repos.update(lang_repos)
                except Exception as e:
                    print(f"Error getting repos for language '{lang}': {e}")
    
    if not all_repos:
        raise ValueError("No repositories to process. Provide repos via --repos, --repo-file, or --languages.")
    
    all_repos = sorted(all_repos)
    print(f"Processing {len(all_repos)} repositories with up to {max_workers} workers per token")
    
    # Get tokens and initialize token manager
    tokens = get_github_token()
    print(f"Using {len(tokens)} GitHub token{'s' if len(tokens) > 1 else ''}")
    
    # Print token information for debugging (first 8 and last 4 chars)
    for i, token in enumerate(tokens):
        print(f"  Token {i+1}: {token[:8]}...{token[-4:]}")
    
    token_manager = TokenManager(tokens)
    processor = ParallelTaskProcessor(token_manager, max_workers=max_workers)
    
    # Process repositories in parallel
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=len(tokens) * max_workers) as executor:
        futures = [
            executor.submit(
                processor.process_repository,
                repo,
                path_prs_abs,
                path_tasks_abs,
                max_pulls,
                cutoff_date
            )
            for repo in all_repos
        ]
        
        # Track results
        success_count = 0
        for future in as_completed(futures):
            result = future.result()
            if result["success"]:
                success_count += 1
    
    end_time = time.time()
    
    # Print final statistics
    print(f"\nProcessing complete in {end_time - start_time:.2f} seconds.")
    print(f"Successfully processed {success_count}/{len(all_repos)} repositories.")
    
    # Print token usage statistics
    usage_stats = token_manager.get_usage_stats()
    print("\nToken usage statistics:")
    for token, usage in usage_stats.items():
        print(f"  {token[:8]}...{token[-4:]}: {usage} requests")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    
    # Repository sources (mutually exclusive)
    repo_group = parser.add_mutually_exclusive_group(required=True)
    repo_group.add_argument(
        "--repos",
        nargs="+",
        help="List of repositories (e.g., 'owner/repo') to process"
    )
    repo_group.add_argument(
        "--languages",
        nargs="+",
        help="Programming languages to fetch top GitHub repos for (e.g., python javascript)"
    )
    repo_group.add_argument(
        "--repo-file",
        help="Path to markdown file containing GitHub repository URLs"
    )
    
    # Path arguments
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_prs = os.path.join(script_dir, "../../data/prs")
    default_tasks = os.path.join(script_dir, "../../data/tasks")
    
    parser.add_argument(
        "--path_prs", 
        default=default_prs,
        help=f"Directory to save PR data (default: {default_prs})"
    )
    parser.add_argument(
        "--path_tasks",
        default=default_tasks,
        help=f"Directory to save task instances (default: {default_tasks})"
    )
    
    # Processing options
    parser.add_argument(
        "--max_pulls", 
        type=int, 
        default=100,
        help="Maximum PRs to fetch per repository"
    )
    parser.add_argument(
        "--cutoff_date",
        help="Only include PRs before this date (YYYYMMDD)"
    )
    parser.add_argument(
        "--max_repos_per_language",
        type=int,
        default=50,
        help="Maximum repositories to fetch per language"
    )
    parser.add_argument(
        "--recency_months", "--months",
        type=int,
        help="Only include repositories updated in the last N months"
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=10,
        help="Maximum concurrent workers per token (default: 10)"
    )
    
    args = parser.parse_args()
    
    # Calculate cutoff date from recency_months if provided
    if args.recency_months and args.recency_months > 0:
        from datetime import datetime, timedelta
        args.cutoff_date = (datetime.now() - timedelta(days=args.recency_months*30)).strftime("%Y%m%d")
        print(f"Using cutoff date: {args.cutoff_date} (last {args.recency_months} months)")
    
    # Run main function
    main(
        repos=args.repos,
        path_prs=args.path_prs,
        path_tasks=args.path_tasks,
        max_pulls=args.max_pulls,
        cutoff_date=args.cutoff_date,
        languages=args.languages,
        max_repos_per_language=args.max_repos_per_language,
        repo_file=args.repo_file,
        recency_months=args.recency_months,
        max_workers=args.max_workers
    )
