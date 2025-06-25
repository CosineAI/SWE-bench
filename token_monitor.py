#!/usr/bin/env python3
"""
Script to explore GitHub tokens and their rate limits.
Shows information about available tokens and their remaining API limits.

Supports both direct GitHub tokens and token service tokens.
"""

import os
import sys
import requests
from datetime import datetime, timezone
from ghapi.core import GhApi
from swebench.collect.token_utils import get_tokens, TokenRotator
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
import time
import argparse


def get_all_tokens():
    """
    Get all available GitHub tokens from both direct token and token service.
    
    Returns:
        list: List of GitHub tokens with their source information
    """
    tokens = []
    
    # Add direct token if available
    direct_token = os.getenv("GITHUB_TOKENS")
    if direct_token and direct_token.strip():
        tokens.append({
            'token': direct_token.strip(),
            'source': 'Direct (GITHUB_TOKENS)'
        })
    
    # Add tokens from token service if available
    team_ids = os.getenv("TEAM_IDS")
    if team_ids:
        try:
            # First try to get tokens directly from the token service
            domain = os.getenv("GHTOKEN_SERVICE_DOMAIN", "https://api.cosine.wtf")
            bearer = os.getenv("GHTOKEN_SERVICE_BEARER")
            
            if bearer:
                slugs = [slug.strip() for slug in team_ids.split(",") if slug.strip()]
                headers = {"Authorization": f"Bearer {bearer}"}
                for slug in slugs:
                    try:
                        url = f"{domain.rstrip('/')}/github/token"
                        resp = requests.get(url, headers=headers, params={"team": slug}, timeout=10)
                        resp.raise_for_status()
                        data = resp.json()
                        token = data.get("token")
                        if token:
                            tokens.append({
                                'token': token,
                                'source': f'Token Service ({slug})',
                                'team': slug
                            })
                    except Exception:
                        continue
            
            # Fall back to the original method if no tokens were found
            if not any('team' in t for t in tokens):
                service_tokens = get_tokens()
                for token in service_tokens:
                    tokens.append({
                        'token': token,
                        'source': 'Token Service (fallback)'
                    })
                    
        except Exception:
            pass
    
    return tokens

def get_token_info(token_info):
    """
    Get rate limit information for a GitHub token.
    
    Args:
        token_info (dict): Dictionary containing 'token' and 'source' keys
        
    Returns:
        dict: Contains rate limit information or error details
    """
    if not token_info or 'token' not in token_info:
        return {
            "error": "Invalid token info",
            "token_preview": "None",
            "source": "Unknown",
            "status": "error"
        }
        
    token = token_info['token']
    token_preview = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "[redacted]"
    
    try:
        api = GhApi(token=token)
        rate_limit = api.rate_limit.get()
        
        core = rate_limit.resources.core
        reset_time = datetime.fromtimestamp(core.reset, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        time_until_reset = reset_time - now
        
        return {
            "remaining": core.remaining,
            "limit": core.limit,
            "reset_time": reset_time,
            "time_until_reset": time_until_reset,
            "used_percent": (1 - (core.remaining / core.limit)) * 100 if core.limit > 0 else 100,
            "token_preview": token_preview,
            "source": token_info.get('source', 'Unknown'),
            "status": "OK"
        }
        
    except Exception as e:
        error_msg = str(e)
        status = "error"
        
        # Handle 401 Unauthorized specifically
        if "401" in error_msg or "Bad credentials" in error_msg:
            error_msg = "Unauthorized - Invalid or expired token"
            status = "invalid"
        elif "rate limit exceeded" in error_msg.lower():
            error_msg = "Rate limit exceeded"
            status = "rate_limited"
        
        return {
            "error": error_msg,
            "token_preview": token_preview,
            "source": token_info.get('source', 'Unknown'),
            "status": status
        }


def create_table(tokens):
    """
    Create a table with token information.
    
    Args:
        tokens (list): List of token info dictionaries
        
    Returns:
        Table: Rich table with token information
    """
    table = Table(
        title="GitHub Token Rate Limit Status", 
        expand=True,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Define columns
    table.add_column("#", style="dim", width=3)
    table.add_column("Source", style="cyan", no_wrap=True, min_width=20)
    table.add_column("Token", style="cyan", no_wrap=True, min_width=15)
    table.add_column("Remaining", style="green", justify="right", min_width=10)
    table.add_column("Limit", style="blue", justify="right", min_width=8)
    table.add_column("Used %", style="yellow", justify="right", min_width=8)
    table.add_column("Resets In", style="magenta", min_width=12)
    table.add_column("Status", style="green", min_width=15)
    
    for idx, token_info in enumerate(tokens, 1):
        info = get_token_info(token_info)
        
        # Handle error cases
        if "error" in info:
            status_style = "red"
            if info.get("status") == "invalid":
                status_style = "bright_red"
            elif info.get("status") == "rate_limited":
                status_style = "yellow"
            
            table.add_row(
                str(idx),
                info.get('source', 'Unknown'),
                info['token_preview'],
                "-", "-", "-", "-",
                f"[{status_style}]{info.get('status', 'error').upper()}: {info['error']}"
            )
            continue
        
        # Handle valid token
        resets_in = str(info["time_until_reset"]).split(".")[0]
        
        # Color coding based on usage
        remaining_style = "green"
        if info['used_percent'] > 80:
            remaining_style = "yellow"
        if info['used_percent'] > 95:
            remaining_style = "red"
        
        table.add_row(
            str(idx),
            info.get('source', 'Unknown'),
            info['token_preview'],
            f"[{remaining_style}]{info['remaining']:,}[/{remaining_style}]",
            f"{info['limit']:,}",
            f"{info['used_percent']:5.1f}%",
            resets_in,
            f"[green]{info.get('status', 'OK')}"
        )
    
    return table


def print_once():
    """
    Print token information once and exit.
    """
    console = Console()
    tokens = get_all_tokens()
    
    if not tokens:
        console.print("[red]No GitHub tokens found. Set GITHUB_TOKENS or configure token service.[/red]")
        return
    
    table = create_table(tokens)
    console.print(table)


def dashboard(refresh_interval=5):
    """
    Live dashboard to monitor GitHub token rate limits.
    Press Ctrl+C to exit.
    """
    console = Console()
    try:
        tokens = get_all_tokens()
        if not tokens:
            console.print("[red]No GitHub tokens found. Set GITHUB_TOKENS or configure token service.[/red]")
            return

        def make_panel():
            tokens = get_all_tokens()
            table = create_table(tokens)
            return Panel(
                table,
                title="GitHub Token Monitor - Press Ctrl+C to exit",
                border_style="blue",
                padding=(1, 2)
            )
        
        with Live(refresh_per_second=1, console=console, screen=True) as live:
            while True:
                live.update(make_panel())
                time.sleep(refresh_interval)
                
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Dashboard stopped by user.[/bold yellow]")
    except Exception as e:
        console.print(f"[red]Error in dashboard: {e}[/red]")


def main():
    parser = argparse.ArgumentParser(description="GitHub Token Explorer")
    parser.add_argument(
        "--dashboard", 
        action="store_true",
        help="Run in dashboard mode with live updates"
    )
    parser.add_argument(
        "--interval", 
        type=int, 
        default=5, 
        help="Dashboard refresh interval in seconds (default: 5)",
        metavar="SECONDS"
    )
    args = parser.parse_args()
    
    try:
        if args.dashboard:
            dashboard(refresh_interval=args.interval)
        else:
            print_once()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()