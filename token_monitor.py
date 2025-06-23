#!/usr/bin/env python3
"""
Script to explore GitHub tokens and their rate limits.
Shows information about available tokens and their remaining API limits.
"""

import os
import sys
import logging
from datetime import datetime, timezone
from ghapi.core import GhApi
from swebench.collect.token_utils import get_tokens, TokenRotator
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
import time
import argparse

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("explore_tokens")

def get_token_info(token):
    """Get rate limit information for a single token."""
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
            "used_percent": (1 - (core.remaining / core.limit)) * 100,
            "token_preview": f"{token[:8]}...{token[-4:]}" if token else "None"
        }
    except Exception as e:
        return {
            "error": str(e),
            "token_preview": f"{token[:8]}...{token[-4:]}" if token else "None"
        }

def check_token_rotator():
    """Check the token rotator configuration and status."""
    try:
        # Try to initialize the token rotator
        rotator = TokenRotator()
        
        print("\n" + "="*80)
        print("TOKEN ROTATOR CONFIGURATION")
        print("="*80)
        print(f"Number of team slugs configured: {len(rotator.slugs)}")
        print(f"Current token index: {rotator.idx}")
        print(f"Cached tokens: {len(rotator.tokens_cache)} out of {len(rotator.slugs)}")
        
        # Get current token info
        current_token = rotator.current_token()
        print(f"\nCurrent token: {current_token[:8]}...{current_token[-4:]}")
        
        # Get rate limit for current token
        current_info = get_token_info(current_token)
        if "error" in current_info:
            print(f"  Error checking rate limit: {current_info['error']}")
        else:
            print(f"  Remaining requests: {current_info['remaining']}/{current_info['limit']} ({current_info['used_percent']:.1f}% used)")
            print(f"  Resets in: {str(current_info['time_until_reset']).split('.')[0]}")
        
        return rotator
    except Exception as e:
        print(f"Error initializing token rotator: {e}")
        return None

def dashboard(refresh_interval=5):
    """
    Live dashboard to monitor GitHub token rate limits.
    Press Ctrl+C to exit.
    """
    console = Console()
    try:
        tokens = get_tokens()
        if not tokens:
            single_token = os.getenv("GITHUB_TOKEN")
            if single_token:
                tokens = [single_token]
            else:
                console.print("[red]No tokens found in environment variables.[/red]")
                return

        def make_table():
            table = Table(title="GitHub Token Rate Limit Dashboard", expand=True)
            table.add_column("Token Preview", style="cyan", no_wrap=True)
            table.add_column("Remaining", style="green")
            table.add_column("Limit", style="magenta")
            table.add_column("Used %", style="yellow")
            table.add_column("Resets In", style="white")
            table.add_column("Status", style="red")
            for token in tokens:
                info = get_token_info(token)
                if "error" in info:
                    table.add_row(
                        info.get("token_preview", "N/A"),
                        "-", "-", "-", "-", f"[red]{info['error']}[/red]"
                    )
                else:
                    resets_in = str(info["time_until_reset"]).split(".")[0]
                    table.add_row(
                        info["token_preview"],
                        str(info["remaining"]),
                        str(info["limit"]),
                        f"{info['used_percent']:.1f}%",
                        resets_in,
                        "[green]OK[/green]"
                    )
            return table

        with Live(Panel(make_table(), title="Press Ctrl+C to exit", border_style="blue"), refresh_per_second=1, console=console) as live:
            while True:
                live.update(Panel(make_table(), title="Press Ctrl+C to exit", border_style="blue"))
                time.sleep(refresh_interval)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Dashboard stopped by user.[/bold yellow]")
    except Exception as e:
        console.print(f"[red]Error in dashboard: {e}[/red]")

def main():
    parser = argparse.ArgumentParser(description="GitHub Token Explorer")
    parser.add_argument("--dashboard", action="store_true", help="Show live dashboard")
    parser.add_argument("--interval", type=int, default=5, help="Dashboard refresh interval (seconds)")
    args = parser.parse_args()

    if args.dashboard:
        dashboard(refresh_interval=args.interval)
        return

    print("="*80)
    print("GITHUB TOKEN EXPLORER")
    print("="*80)
    
    # Check environment variables
    print("\nENVIRONMENT VARIABLES")
    print("-"*40)
    print(f"GITHUB_TOKENS: {'Set' if os.getenv('GITHUB_TOKENS') else 'Not set'}")
    print(f"GITHUB_TOKEN: {'Set' if os.getenv('GITHUB_TOKEN') else 'Not set'}")
    print(f"TEAM_IDS: {'Set' if os.getenv('TEAM_IDS') else 'Not set'}")
    
    # Get tokens using the project's token utilities
    print("\nTOKEN INFORMATION")
    print("-"*40)
    
    try:
        tokens = get_tokens()
        if not tokens:
            print("No tokens found via get_tokens()")
            # Try to get single token from environment
            single_token = os.getenv("GITHUB_TOKEN")
            if single_token:
                tokens = [single_token]
                print("Using single token from GITHUB_TOKEN")
            else:
                print("No tokens found in environment variables")
                return
        
        print(f"Found {len(tokens)} token(s):")
        
        # Check rate limits for each token
        for i, token in enumerate(tokens, 1):
            print(f"\nToken {i}:")
            info = get_token_info(token)
            
            if "error" in info:
                print(f"  Error: {info['error']}")
            else:
                print(f"  Preview: {info['token_preview']}")
                print(f"  Remaining requests: {info['remaining']}/{info['limit']} ({info['used_percent']:.1f}% used)")
                print(f"  Resets at: {info['reset_time']} (in {str(info['time_until_reset']).split('.')[0]})")
    
    except Exception as e:
        print(f"Error getting token information: {e}")
    
    # Check token rotator if TEAM_IDS is set
    if os.getenv("TEAM_IDS"):
        check_token_rotator()
    
    print("\n" + "="*80)
    print("EXPLORATION COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()
