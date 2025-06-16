from __future__ import annotations


import logging
import re
import requests
import time

from bs4 import BeautifulSoup
from ghapi.core import GhApi
from fastcore.net import HTTP404NotFoundError, HTTP403ForbiddenError, HTTP401UnauthorizedError
from typing import Callable, Iterator, Optional
from unidiff import PatchSet

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/using-keywords-in-issues-and-pull-requests
PR_KEYWORDS = {
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
}


class Repo:
    def __init__(self, owner: str, name: str, token: Optional[str] = None, token_rotator=None):
        """
        Init to retrieve target repository and create ghapi tool

        Args:
            owner (str): owner of target repository
            name (str): name of target repository
            token (str): github token (optional if using token rotation)
            token_rotator: TokenRotator instance (optional)
        """
        self.owner = owner
        self.name = name
        self.token = token
        # TokenRotator instance for rotating tokens on 403 errors
        self.token_rotator = token_rotator
        self.api = GhApi(token=token if token else (token_rotator.current_token() if token_rotator else None))
        self.repo = self.call_api(self.api.repos.get, owner=owner, repo=name)

    def call_api(self, func: Callable, **kwargs) -> dict | None:
        """
        API call wrapper with rate limit and token rotation handling,
        with improved 401 handling: refresh token once, then invalidate if still 401.

        Args:
            func (callable): API function to call
            **kwargs: keyword arguments to pass to API function
        Return:
            values (dict): response object of `func`
        """
        # Import here to avoid circular import at module level
        token_rotator = self.token_rotator
        if token_rotator is None:
            try:
                from swebench.collect.token_utils import token_rotator as global_token_rotator
                token_rotator = global_token_rotator
            except Exception:
                token_rotator = None

        attempt = 0
        last_403 = False
        attempt_401 = 0
        refreshed_for_slug = None

        while True:
            max_attempts = token_rotator.num_tokens() if token_rotator else 1
            if attempt >= max_attempts:
                break
            slug_before = None
            if token_rotator:
                with token_rotator.lock:
                    if token_rotator.slugs:
                        slug_before = token_rotator.slugs[token_rotator.idx]
            try:
                values = func(**kwargs)
                return values
            except HTTP403ForbiddenError:
                last_403 = True
                if not token_rotator:
                    # Fall back to old behavior: wait for rate limit
                    while True:
                        rl = self.api.rate_limit.get()
                        logger.info(
                            f"[{self.owner}/{self.name}] Rate limit exceeded for token {str(self.token)[:10]}, "
                            f"waiting for 5 minutes, remaining calls: {rl.resources.core.remaining}"
                        )
                        if rl.resources.core.remaining > 0:
                            break
                        time.sleep(60 * 5)
                    continue
                else:
                    # Try next token
                    old_token = self.token
                    try:
                        new_token = token_rotator.next_token()
                    except RuntimeError:
                        logger.error(
                            f"[{self.owner}/{self.name}] All tokens exhausted (403)."
                        )
                        return None
                    self.api = GhApi(token=new_token)
                    self.token = new_token
                    logger.info(
                        f"[{self.owner}/{self.name}] Switched token due to 403 (attempt {attempt+1}/{max_attempts}, slug '{slug_before}')."
                    )
                    attempt += 1
                    continue
            except HTTP401UnauthorizedError:
                if not token_rotator:
                    logger.error(
                        f"[{self.owner}/{self.name}] Unauthorized (401) and no token rotator available."
                    )
                    raise
                else:
                    # On first 401, try to refresh the token for the *current* slug and retry once
                    if attempt_401 == 0:
                        logger.warning(
                            f"[{self.owner}/{self.name}] 401 Unauthorized for slug '{slug_before}'. Attempting token refresh."
                        )
                        try:
                            refreshed_token = token_rotator.refresh_current_token()
                            self.api = GhApi(token=refreshed_token)
                            self.token = refreshed_token
                            refreshed_for_slug = slug_before
                            attempt_401 += 1
                            continue  # Retry immediately with refreshed token
                        except Exception as e:
                            logger.error(
                                f"[{self.owner}/{self.name}] Failed to refresh token for slug '{slug_before}': {e}"
                            )
                            # If refresh fails, proceed to invalidate below
                    # If already refreshed once (or refresh failed), invalidate slug and rotate
                    logger.warning(
                        f"[{self.owner}/{self.name}] 401 Unauthorized after refresh for slug '{slug_before}'. Invalidating and rotating token."
                    )
                    token_rotator.invalidate_current_token(slug=slug_before)
                    if token_rotator.num_tokens() == 0:
                        logger.error(
                            f"[{self.owner}/{self.name}] All tokens exhausted (401)."
                        )
                        raise RuntimeError(f"[{self.owner}/{self.name}] All tokens exhausted (401).")
                    # After invalidation, get the current token (do not rotate yet)
                    new_token = token_rotator.current_token()
                    with token_rotator.lock:
                        slugs_left = list(token_rotator.slugs)
                        slug_now = token_rotator.slugs[token_rotator.idx] if token_rotator.slugs else None
                    self.api = GhApi(token=new_token)
                    self.token = new_token
                    logger.info(
                        f"[{self.owner}/{self.name}] Invalidated token for slug '{slug_before}', using new token for slug '{slug_now}', {len(slugs_left)} tokens left."
                    )
                    attempt_401 = 0  # Reset for next slug
                    continue
            except HTTP404NotFoundError:
                logger.info(f"[{self.owner}/{self.name}] Resource not found {kwargs}")
                return None
            except Exception as e:
                logger.error(f"[{self.owner}/{self.name}] Unhandled error in call_api: {e}")
                raise
        # If we reach here, all tokens exhausted or repeated rate limit
        if last_403 and token_rotator:
            logger.error(
                f"[{self.owner}/{self.name}] All tokens exhausted (403)."
            )
        return None

    def extract_resolved_issues(self, pull: dict) -> list[str]:
        """
        Extract list of issues referenced by a PR

        Args:
            pull (dict): PR dictionary object from GitHub
        Return:
            resolved_issues (list): list of issue numbers referenced by PR
        """
        # Define 1. issue number regex pattern 2. comment regex pattern 3. keywords
        issues_pat = re.compile(r"(\w+)\s+\#(\d+)")
        comments_pat = re.compile(r"(?s)<!--.*?-->")

        # Construct text to search over for issue numbers from PR body and commit messages
        text = pull.title if pull.title else ""
        text += "\n" + (pull.body if pull.body else "")
        commits = self.get_all_loop(
            self.api.pulls.list_commits, pull_number=pull.number, quiet=True
        )
        commit_messages = [commit.commit.message for commit in commits]
        commit_text = "\n".join(commit_messages) if commit_messages else ""
        text += "\n" + commit_text
        # Remove comments from text
        text = comments_pat.sub("", text)
        # Look for issue numbers in text via scraping <keyword, number> patterns
        references = issues_pat.findall(text)
        resolved_issues_set = set()
        if references:
            for word, issue_num in references:
                if word.lower() in PR_KEYWORDS:
                    resolved_issues_set.add(issue_num)
        return list(resolved_issues_set)

    def get_all_loop(
        self,
        func: Callable,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        quiet: bool = False,
        **kwargs,
    ) -> Iterator:
        """
        Return all values from a paginated API endpoint.

        Args:
            func (callable): API function to call
            per_page (int): number of values to return per page
            num_pages (int): number of pages to return
            quiet (bool): whether to print progress
            **kwargs: keyword arguments to pass to API function
        """
        page = 1
        args = {
            "owner": self.owner,
            "repo": self.name,
            "per_page": per_page,
            **kwargs,
        }
        while True:
            try:
                # Get values from API call
                values = func(**args, page=page)
                yield from values
                if len(values) == 0:
                    break
                if not quiet:
                    rl = self.api.rate_limit.get()
                    logger.info(
                        f"[{self.owner}/{self.name}] Processed page {page} ({per_page} values per page). "
                        f"Remaining calls: {rl.resources.core.remaining}"
                    )
                if num_pages is not None and page >= num_pages:
                    break
                page += 1
            except Exception as e:
                # Rate limit handling
                logger.error(
                    f"[{self.owner}/{self.name}] Error processing page {page} "
                    f"w/ token {self.token[:10]} - {e}"
                )
                # --- PATCH: rotate token on 401s, and patch call to use call_api for rate_limit ---
                from fastcore.net import HTTP401UnauthorizedError  # already imported above, but safe

                # If RuntimeError (from all tokens exhausted or unauthorized), bubble up to skip repo
                if isinstance(e, RuntimeError):
                    raise

                # Handle HTTP401UnauthorizedError for token rotation
                if isinstance(e, HTTP401UnauthorizedError):
                    token_rotator = getattr(self, "token_rotator", None)
                    if token_rotator:
                        token_rotator.invalidate_current_token()
                        if token_rotator.num_tokens() == 0:
                            raise
                        self.api = GhApi(token=token_rotator.current_token())
                        self.token = token_rotator.current_token()
                        logger.info(
                            f"[{self.owner}/{self.name}] Rotated token due to 401 Unauthorized. "
                            f"New token: {self.token}..."
                        )
                        continue  # retry same page without incrementing

                while True:
                    rl = self.call_api(self.api.rate_limit.get)
                    if rl is None:
                        logger.error(f"[{self.owner}/{self.name}] Unable to fetch rate limit; all tokens exhausted or unauthorized.")
                        raise RuntimeError("All tokens exhausted or unauthorized")
                    if rl.resources.core.remaining > 0:
                        break
                    logger.info(
                        f"[{self.owner}/{self.name}] Waiting for rate limit reset "
                        f"for token {self.token}, checking again in 5 minutes"
                        f"{rl}"
                    )
                    time.sleep(60 * 5)
        if not quiet:
            logger.info(
                f"[{self.owner}/{self.name}] Processed {(page - 1) * per_page + len(values)} values"
            )

    def get_all_issues(
        self,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Wrapper for API call to get all issues from repo

        Args:
            per_page (int): number of issues to return per page
            num_pages (int): number of pages to return
            direction (str): direction to sort issues
            sort (str): field to sort issues by
            state (str): state of issues to look for
            quiet (bool): whether to print progress
        """
        issues = self.get_all_loop(
            self.api.issues.list_for_repo,
            num_pages=num_pages,
            per_page=per_page,
            direction=direction,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return issues

    def get_all_pulls(
        self,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Wrapper for API call to get all PRs from repo

        Args:
            per_page (int): number of PRs to return per page
            num_pages (int): number of pages to return
            direction (str): direction to sort PRs
            sort (str): field to sort PRs by
            state (str): state of PRs to look for
            quiet (bool): whether to print progress
        """
        pulls = self.get_all_loop(
            self.api.pulls.list,
            num_pages=num_pages,
            direction=direction,
            per_page=per_page,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return pulls


def extract_problem_statement_and_hints(pull: dict, repo: Repo) -> tuple[str, str]:
    """
    Extract problem statement from issues associated with a pull request

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
    Return:
        text (str): problem statement
        hints (str): hints
    """
    if repo.name == "django":
        return extract_problem_statement_and_hints_django(pull, repo)
    text = ""
    all_hint_texts = list()
    for issue_number in pull["resolved_issues"]:
        issue = repo.call_api(
            repo.api.issues.get,
            owner=repo.owner,
            repo=repo.name,
            issue_number=issue_number,
        )
        if issue is None:
            continue
        title = issue.title if issue.title else ""
        body = issue.body if issue.body else ""
        text += f"{title}\n{body}\n"
        issue_number = issue.number
        hint_texts = _extract_hints(pull, repo, issue_number)
        hint_text = "\n".join(hint_texts)
        all_hint_texts.append(hint_text)
    return text, "\n".join(all_hint_texts) if all_hint_texts else ""


def _extract_hints(pull: dict, repo: Repo, issue_number: int) -> list[str]:
    """
    Extract hints from comments associated with a pull request (before first commit)

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
        issue_number (int): issue number
    Return:
        hints (list): list of hints
    """
    # Get all commits in PR
    commits = repo.get_all_loop(
        repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
    )
    commits = list(commits)
    if len(commits) == 0:
        # If there are no comments, return no hints
        return []
    # Get time of first commit in PR
    commit_time = commits[0].commit.author.date  # str
    commit_time = time.mktime(time.strptime(commit_time, "%Y-%m-%dT%H:%M:%SZ"))
    # Get all comments in PR
    all_comments = repo.get_all_loop(
        repo.api.issues.list_comments, issue_number=issue_number, quiet=True
    )
    all_comments = list(all_comments)
    # Iterate through all comments, only keep comments created before first commit
    comments = list()
    for comment in all_comments:
        comment_time = time.mktime(
            time.strptime(comment.updated_at, "%Y-%m-%dT%H:%M:%SZ")
        )  # use updated_at instead of created_at
        if comment_time < commit_time:
            comments.append(comment)
        else:
            break
        # only include information available before the first commit was created
    # Keep text from comments
    comments = [comment.body for comment in comments]
    return comments


def extract_patches(pull: dict, repo: Repo) -> tuple[str, str]:
    """
    Get patch and test patch from PR

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
    Return:
        patch_change_str (str): gold patch
        patch_test_str (str): test patch
    """
    patch = requests.get(pull["diff_url"]).text
    patch_test = ""
    patch_fix = ""
    for hunk in PatchSet(patch):
        path_lower = hunk.path.lower()
        if any(word in path_lower for word in ("test", "tests", "e2e", "testing")):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)
    return patch_fix, patch_test


### MARK: Repo Specific Parsing Functions ###
def extract_problem_statement_and_hints_django(
    pull: dict, repo: Repo
) -> tuple[str, list[str]]:
    """
    Get problem statement and hints from issues associated with a pull request

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
    Return:
        text (str): problem statement
        hints (str): hints
    """
    text = ""
    all_hints_text = list()
    for issue_number in pull["resolved_issues"]:
        url = f"https://code.djangoproject.com/ticket/{issue_number}"
        resp = requests.get(url)
        if resp.status_code != 200:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        # Get problem statement (title + body)
        issue_desc = soup.find("div", {"id": "ticket"})
        title = issue_desc.find("h1", class_="searchable").get_text()
        title = re.sub(r"\s+", " ", title).strip()
        body = issue_desc.find("div", class_="description").get_text()
        body = re.sub(r"\n+", "\n", body)
        body = re.sub(r"    ", "\t", body)
        body = re.sub(r"[ ]{2,}", " ", body).strip()
        text += f"{title}\n{body}\n"

        # Get time of first commit in PR
        commits = repo.get_all_loop(
            repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
        )
        commits = list(commits)
        if len(commits) == 0:
            continue
        commit_time = commits[0].commit.author.date
        commit_time = time.mktime(time.strptime(commit_time, "%Y-%m-%dT%H:%M:%SZ"))

        # Get all comments before first commit
        comments_html = soup.find("div", {"id": "changelog"})
        div_blocks = comments_html.find_all("div", class_="change")
        # Loop through each div block
        for div_block in div_blocks:
            # Find the comment text and timestamp
            comment_resp = div_block.find("div", class_="comment")
            timestamp_resp = div_block.find("a", class_="timeline")
            if comment_resp is None or timestamp_resp is None:
                continue

            comment_text = re.sub(r"\s+", " ", comment_resp.text).strip()
            timestamp = timestamp_resp["title"]
            if timestamp.startswith("See timeline at "):
                timestamp = timestamp[len("See timeline at ") :]
            if "/" in timestamp:
                timestamp = time.mktime(time.strptime(timestamp, "%m/%d/%y %H:%M:%S"))
            elif "," in timestamp:
                timestamp = time.mktime(
                    time.strptime(timestamp, "%b %d, %Y, %I:%M:%S %p")
                )
            else:
                raise ValueError(f"Timestamp format not recognized: {timestamp}")

            # Append the comment and timestamp as a tuple to the comments list
            if timestamp < commit_time:
                all_hints_text.append((comment_text, timestamp))

    return text, all_hints_text
