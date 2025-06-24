#!/usr/bin/env python3
import re
from pathlib import Path

def format_repositories():
    with open('repository_base/repolist.md', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split content by language sections
    sections = re.split(r'##\s+', content)[1:]  # Skip first empty part
    
    with open('repository_base/tasks.md', 'w', encoding='utf-8') as f:
        for section in sections:
            if not section.strip():
                continue
                
            # Get language name (first line)
            lines = section.split('\n')
            language = lines[0].strip()
            
            # Find all repository links
            f.write(f"## {language}\n")
            for line in lines[1:]:
                match = re.search(r'\*\s*\[.*?\]\((https?://github\.com/[^\s)]+)\)|\*\s*(https?://github\.com/\S+)', line)
                if match:
                    # Use the first non-None group (handles both [text](url) and plain url formats)
                    url = next((g for g in match.groups() if g), None)
                    if url:
                        f.write(f"- {url}\n")
            f.write("\n")

if __name__ == "__main__":
    format_repositories()
    print("Formatted repositories written to tasks.md")
