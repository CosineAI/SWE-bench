#!/usr/bin/env python3
"""
Script to explore GitHub tokens and their rate limits.
Shows information about available tokens and their remaining API limits.

Supports both direct GitHub tokens and token service tokens.
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
from rich import print as rprint
import time
import argparse

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("github_token_monitor")


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
            service_tokens = get_tokens()
            for token in service_tokens:
                tokens.append({
                    'token': token,
                    'source': 'Token Service'
                })
        except Exception as e:
            logger.warning(f"Could not get tokens from token service: {e}")
    
    if not tokens:
        logger.warning("No GitHub tokens found. Set GITHUB_TOKENS or configure token service with TEAM_IDS and SERVICE_AUTH.")
    
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

def check_token_rotator():
    """Check if token rotator is working correctly."""
    console = Console()
    
    try:
        # Get all available tokens first
        all_tokens = get_all_tokens()
        if not all_tokens:
            console.print("[red]No tokens available for rotation[/red]")
            return False
        
        # Create a token rotator instance
        rotator = TokenRotator()
        
        # Get the current token and its info
        try:
            current_token = rotator.current_token()
            token_source = next((t['source'] for t in all_tokens if t.get('token') == current_token), 'Unknown')
            
            # Display rotator info
            console.print("[bold]Token Rotator Status:[/bold]")
            console.print(f"  • Total tokens: {len(all_tokens)}")
            console.print(f"  • Current token source: {token_source}")
            
            # Test rotation
            console.print("\n[bold]Testing token rotation:[/bold]")
            seen_tokens = set()
            
            # Get current token
            try:
                # Get initial token
                current = rotator.current_token()
                if current:
                    seen_tokens.add(current)
                    preview = f"{current[:8]}...{current[-4:]}"
                    source = next((t['source'] for t in all_tokens if t.get('token') == current), 'Unknown')
                    console.print(f"  1. Current token: {preview} (from {source})")
                
                # Manually rotate through tokens by updating the index
                for i in range(1, min(3, len(all_tokens))):  # Show up to 3 tokens
                    try:
                        # Update the index and get the next token
                        with rotator.lock:
                            rotator.idx = (rotator.idx + 1) % len(rotator.slugs)
                            next_token = rotator.current_token()
                        
                        if not next_token:
                            console.print(f"  {i+1}. [yellow]No more tokens available[/yellow]")
                            break
                            
                        token_preview = f"{next_token[:8]}...{next_token[-4:]}"
                        token_source = next((t['source'] for t in all_tokens if t.get('token') == next_token), 'Unknown')
                        
                        if next_token in seen_tokens:
                            console.print(f"  {i+1}. [yellow]Token {token_preview} (from {token_source}) already seen - rotation may not be working correctly[/yellow]")
                            break
                        else:
                            console.print(f"  {i+1}. Next token: {token_preview} (from {token_source})")
                            seen_tokens.add(next_token)
                            
                    except Exception as e:
                        console.print(f"  {i+1}. [red]Error getting next token: {e}[/red]")
                        break
                        
            except Exception as e:
                console.print(f"[red]Error during token rotation test: {e}[/red]")
                logger.exception("Error during token rotation test")
            
            # Check rotation results
            if len(seen_tokens) > 1:
                console.print("  [green]✓ Token rotation is working correctly[/green]")
            else:
                console.print("  [yellow]⚠ Token rotation may not be working as expected[/yellow]")
            
            # Get rate limit for current token
            current_token = rotator.current_token()
            if current_token:
                token_info = next((t for t in all_tokens if t.get('token') == current_token), {})
                info = get_token_info({"token": current_token, "source": token_info.get('source', 'Unknown')})
                
                console.print("\n[bold]Current Token Rate Limit:[/bold]")
                if "error" in info:
                    status_style = "red"
                    if info.get("status") == "invalid":
                        status_style = "bright_red"
                    elif info.get("status") == "rate_limited":
                        status_style = "yellow"
                        
                    console.print(f"  • Status: [{status_style}]{info['status'].upper()}: {info['error']}[/{status_style}]")
                else:
                    remaining_style = "green"
                    if info['used_percent'] > 80:
                        remaining_style = "yellow"
                    if info['used_percent'] > 95:
                        remaining_style = "red"
                    
                    console.print(f"  • Remaining: [{remaining_style}]{info['remaining']:,}[/{remaining_style}] / {info['limit']:,} ({info['used_percent']:.1f}% used)")
                    console.print(f"  • Resets in: {info['time_until_reset']}")
            
            return True
            
        except Exception as e:
            console.print(f"[red]Error checking token rotator: {e}[/red]")
            logger.exception("Error in token rotator check")
            return False
            
    except Exception as e:
        console.print(f"[red]Error initializing token rotator: {e}[/red]")
        logger.exception("Error initializing token rotator")
        return False
                
def dashboard(refresh_interval=2):
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

        def make_table():
            table = Table(
                title="GitHub Token Rate Limit Dashboard", 
                expand=True,
                show_header=True,
                header_style="bold magenta"
            )
            
            # Define columns
            table.add_column("Source", style="cyan", no_wrap=True, min_width=20)
            table.add_column("Token", style="cyan", no_wrap=True, min_width=15)
            table.add_column("Remaining", style="green", justify="right", min_width=10)
            table.add_column("Limit", style="magenta", justify="right", min_width=10)
            table.add_column("Used %", style="yellow", justify="right", min_width=10)
            table.add_column("Resets In", style="white", min_width=15)
            table.add_column("Status", style="red", min_width=20)
            
            for token_info in tokens:
                info = get_token_info(token_info)
                
                # Handle error cases
                if "error" in info:
                    status_style = "red"
                    if info.get("status") == "invalid":
                        status_style = "bright_red"
                    elif info.get("status") == "rate_limited":
                        status_style = "yellow"
                    
                    table.add_row(
                        info.get("source", "Unknown"),
                        info["token_preview"],
                        "-", "-", "-", "-",
                        f"[{status_style}]{info.get('status', 'error').upper()}: {info['error']}[/{status_style}]"
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
                    info.get("source", "Unknown"),
                    info["token_preview"],
                    f"[{remaining_style}]{info['remaining']:,}[/{remaining_style}]",
                    f"{info['limit']:,}",
                    f"{info['used_percent']:5.1f}%",
                    resets_in,
                    f"[green]{info.get('status', 'OK')}"
                )
                
            return table

        # Create a panel with a border and title
        panel = Panel(
            make_table(),
            title="GitHub Token Monitor - Press Ctrl+C to exit",
            border_style="blue",
            padding=(1, 2)
        )
        
        with Live(refresh_per_second=1, console=console, screen=True) as live:
            while True:
                # Create a new panel with fresh data on each iteration
                tokens = get_all_tokens()
                if tokens:
                    new_panel = Panel(
                        make_table(),
                        title="GitHub Token Monitor - Press Ctrl+C to exit",
                        border_style="blue",
                        padding=(1, 2)
                    )
                    live.update(new_panel)
                time.sleep(refresh_interval)
                
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Dashboard stopped by user.[/bold yellow]")
    except Exception as e:
        console.print(f"[red]Error in dashboard: {e}[/red]")
        logger.exception("Error in dashboard")
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Dashboard stopped by user.[/bold yellow]")
    except Exception as e:
        console.print(f"[red]Error in dashboard: {e}[/red]")

def main():
    parser = argparse.ArgumentParser(description="GitHub Token Explorer")
    parser.add_argument(
        "--dashboard", 
        action="store_true", 
        help="Show live dashboard with token usage information"
    )
    parser.add_argument(
        "--rotator", 
        action="store_true", 
        help="Test token rotator functionality"
    )
    parser.add_argument(
        "--interval", 
        type=int, 
        default=5, 
        help="Dashboard refresh interval in seconds (default: 5)",
        metavar="SECONDS"
    )
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Set log level
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    # If dashboard mode is requested
    if args.dashboard:
        dashboard(refresh_interval=args.interval)
        return
    
    # If rotator test is requested
    if args.rotator:
        check_token_rotator()
        return
    
    console = Console()
    
    # Print header
    console.rule("GitHub Token Explorer", style="bold blue")
    
    # Check environment variables
    console.print("\n[bold]ENVIRONMENT VARIABLES[/bold]")
    console.print("-" * 40)
    console.print(f"GITHUB_TOKENS: {'[green]Set' if os.getenv('GITHUB_TOKENS') else '[red]Not set'}")
    console.print(f"TEAM_IDS: {'[green]Set' if os.getenv('TEAM_IDS') else '[red]Not set'}")
    
    # Get all available tokens
    console.print("\n[bold]TOKEN INFORMATION[/bold]")
    console.print("-" * 40)
    
    try:
        tokens = get_all_tokens()
        if not tokens:
            console.print("[red]No GitHub tokens found.[/red]")
            console.print("\n[bold]TROUBLESHOOTING[/bold]")
            console.print("-" * 40)
            console.print("1. Set GITHUB_TOKENS environment variable for direct token access")
            console.print("2. Or configure token service with TEAM_IDS and SERVICE_AUTH")
            return
        
        console.print(f"Found {len(tokens)} token(s):")
        
        # Check rate limits for each token
        for i, token_info in enumerate(tokens, 1):
            console.print(f"\n[bold]Token {i}: {token_info['source']}[/bold]")
            info = get_token_info(token_info)
            
            if "error" in info:
                status_style = "red"
                if info.get("status") == "invalid":
                    status_style = "bright_red"
                elif info.get("status") == "rate_limited":
                    status_style = "yellow"
                
                console.print(f"  [red]Error:[/red] [{status_style}]{info['error']}[/{status_style}]")
                console.print(f"  Preview: {info['token_preview']}")
            else:
                console.print(f"  Preview: {info['token_preview']}")
                console.print(f"  Remaining requests: [green]{info['remaining']:,}[/green] / {info['limit']:,} "
                             f"({info['used_percent']:.1f}% used)")
                console.print(f"  Resets at: {info['reset_time']} (in {str(info['time_until_reset']).split('.')[0]})")
    
    except Exception as e:
        console.print(f"[red]Error getting token information: {e}[/red]")
        logger.exception("Error in main")
    
    console.print("\n" + "="*80)
    console.print("EXPLORATION COMPLETE", style="bold green")
    console.print("="*80)

if __name__ == "__main__":
    main()
