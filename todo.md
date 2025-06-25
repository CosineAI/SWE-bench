### Collection pipeline

1. Extend the pipeline to do multitask - most of this is already done by genie.
2. Get the collection pipeline working
    - Adapt it for concurrent running across all different token styles.
3. With all the data collected, make swe-benchv2 (so to say)
4. Compare all the fields and make sure everything is same with the original swe-bench.

### Docker Testing pipeline

1. Understand how the docker works with the normal dataset.
2. See the issues with new dataset.
3. Get the dictionary ready, the one Ali explained to me. 

# Steps

## Data Collection

1. Begin with setting up the .env

    ```bash
    GHTOKEN_SERVICE_BEARER=
    TEAM_IDS=
    GHTOKEN_SERVICE_DOMAIN=
    GITHUB_TOKEN=
    ```

2. Create folders for the prs collected and tasks generated. 

    ```bash
    mkdir -p data/prs data/tasks
    ```

3. [optional] Create your custom repo list `repo_collection/repo_list.json`

    ```json
    {
    "Python": [
        "https://github.com/psf/requests",
        "https://github.com/pandas-dev/pandas",
        // ... more repositories
    ],
    // ... more languages
    }
    ```

4. [optional] Create a token monitor `token_monitor.py` to monitor the token usage from various styles of tokens. Good to launch when you run `get_tasks_pipeline.py`. Please also consider the changes made to `swebench/collect/token_utils.py`.

5. Next, run `compare.py` to compare the original dataset with the new dataset. `compare.py` also takes care of making the dataset from `data/tasks` and saving it to `swebench_v2.jsonl`.

This is how the output looks from `compare.py`:

```bash
python compare.py
Loading original SWE-bench dataset...
Original SWE-bench test set size: 2294 tasks

Original dataset fields: {'environment_setup_commit', 'problem_statement', 'patch', 'test_patch', 'hints_text', 'PASS_TO_PASS', 'created_at', 'repo', 'FAIL_TO_PASS', 'instance_id', 'version', 'base_commit'}

Processing task files...

Converted 77 tasks to SWE-bench v2 format

==================================================
VALIDATION CHECKS
==================================================

✅ Field structure matches original SWE-bench format

✅ All required fields present and valid

✅ All list fields properly formatted

✅ All instance IDs are unique and properly formatted

==================================================
✅ ALL VALIDATIONS PASSED
Dataset is ready to use as a drop-in replacement for SWE-bench!

Task counts by repository (28 repositories):
  AdguardTeam/AdGuardHome: 1 tasks
  All-Hands-AI/OpenHands: 3 tasks
  AntonOsika/gpt-engineer: 1 tasks
  BookStackApp/BookStack: 3 tasks
  BurntSushi/ripgrep: 1 tasks
  ClickHouse/ClickHouse: 2 tasks
  DIYgod/RSSHub: 1 tasks
  DioxusLabs/dioxus: 4 tasks
  FuelLabs/fuel-core: 9 tasks
  FuelLabs/fuels-rs: 4 tasks
  FuelLabs/sway: 4 tasks
  Genymobile/scrcpy: 6 tasks
  HeyPuter/puter: 1 tasks
  HigherOrderCO/Bend: 9 tasks
  Homebrew/brew: 1 tasks
  Intervention/image: 2 tasks
  Kong/insomnia: 2 tasks
  LadybirdBrowser/ladybird: 4 tasks
  Leaflet/Leaflet: 1 tasks
  OpenAPITools/openapi-generator: 1 tasks
  PHP-CS-Fixer/PHP-CS-Fixer: 4 tasks
  RustPython/RustPython: 2 tasks
  Schniz/fnm: 2 tasks
  Seldaek/monolog: 2 tasks
  SpartnerNL/Laravel-Excel: 2 tasks
  YOURLS/YOURLS: 1 tasks
  activerecord-hackery/ransack: 2 tasks
  alibaba/Sentinel: 2 tasks

Converted tasks saved to: /Users/soumyakundu/SWE-bench/swebench_v2.jsonl
```

**ISSUES:** 
1. Right now, when you run `get_tasks_pipeline.py`, it simply continues triggering requests raising 403's. Need code to monitor this and run it properly, perenially.

## Docker env creation for each and every task.

To be done.

# Changes

1. Add the option to ingest custom repo list into `get_tasks_pipeline.py`.p

# Todo

Look into the below code. Maybe we can make a better dataset with the logic below.

```python
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Tuple
from collections import defaultdict
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from datasets import load_dataset
from tqdm import tqdm

def load_tasks(tasks_dir: str) -> List[Dict[str, Any]]:
    """Load all task instances from the tasks directory."""
    tasks = []
    tasks_path = Path(tasks_dir)
    
    # Process each .jsonl file in the tasks directory
    for task_file in tasks_path.glob("*.jsonl"):
        # Skip .all files as they contain duplicates
        if task_file.name.endswith('.all.jsonl'):
            continue
            
        with open(task_file, 'r') as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))
    
    return tasks

def convert_to_swebench_format(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert tasks to SWE-bench format."""
    swebench_tasks = []
    
    for task in tasks:
        swebench_task = {
            "repo": task.get("repo", ""),
            "instance_id": task.get("instance_id", ""),
            "base_commit": task.get("base_commit", ""),
            "patch": task.get("patch", ""),
            "test_patch": task.get("test_patch", ""),
            "testcases": task.get("test_cases", []),
            "version": "2.0",  # Marking as SWE-bench v2
            "created_at": "2025-06-25",
            "pull_number": task.get("pull_number", 0),
            "issue_numbers": task.get("issue_numbers", []),
            "problem_statement": task.get("problem_statement", ""),
            "hints_text": task.get("hints_text", ""),
            "repo_description": task.get("repo_description", ""),
            "fail_to_pass": task.get("fail_to_pass", []),
            "pass_to_pass": task.get("pass_to_pass", []),
            "environment_setup_commit": task.get("environment_setup_commit", ""),
        }
        swebench_tasks.append(swebench_task)
    
    return swebench_tasks

def main():
    # Load original SWE-bench dataset
    print("Loading original SWE-bench dataset...")
    try:
        original_dataset = load_dataset("princeton-nlp/SWE-bench", split="test")
        print(f"Original SWE-bench test set size: {len(original_dataset)} tasks")
    except Exception as e:
        print(f"Error loading original SWE-bench dataset: {e}")
        original_dataset = None
    
    # Load and convert tasks
    print("\nProcessing task files...")
    tasks_dir = os.path.join(os.path.dirname(__file__), "tasks")
    tasks = load_tasks(tasks_dir)
    swebench_tasks = convert_to_swebench_format(tasks)
    
    print(f"\nConverted {len(swebench_tasks)} tasks to SWE-bench v2 format")
    
    # Count by repo
    repo_counts = {}
    for task in swebench_tasks:
        repo = task['repo']
        repo_counts[repo] = repo_counts.get(repo, 0) + 1
    
    print("\nTask counts by repository:")
    for repo, count in sorted(repo_counts.items()):
        print(f"{repo}: {count} tasks")
    
    # Save the converted tasks
    output_file = os.path.join(os.path.dirname(__file__), "swebench_v2.jsonl")
    with open(output_file, 'w') as f:
        for task in swebench_tasks:
            f.write(json.dumps(task) + '\n')
    
    print(f"\nConverted tasks saved to: {output_file}")
    
    # Perform similarity analysis
    if len(swebench_tasks) > 1:  # Need at least 2 tasks for similarity
        analyze_task_similarity(swebench_tasks)

def preprocess_text(text: str) -> str:
    """Basic text preprocessing for similarity comparison."""
    if not isinstance(text, str):
        return ""
    # Convert to lowercase and remove some common code symbols
    return ' '.join(text.lower().split())

def analyze_task_similarity(tasks: List[Dict[str, Any]], similarity_threshold: float = 0.8) -> None:
    """
    Analyze similarity between tasks using TF-IDF and cosine similarity.
    
    Args:
        tasks: List of task dictionaries
        similarity_threshold: Threshold for considering tasks similar (0.0 to 1.0)
    """
    print("\nAnalyzing task similarity...")
    
    # Extract text fields for similarity comparison
    task_texts = []
    for task in tasks:
        # Combine relevant fields for similarity comparison
        text_parts = []
        for field in ['problem_statement', 'hints_text', 'repo_description']:
            if field in task and task[field]:
                text_parts.append(str(task[field]))
        
        # Add test cases if available
        if 'testcases' in task and task['testcases']:
            if isinstance(task['testcases'], list):
                text_parts.extend([str(tc) for tc in task['testcases'] if tc])
            else:
                text_parts.append(str(task['testcases']))
                
        task_text = ' '.join(text_parts)
        task_texts.append(preprocess_text(task_text))
    
    # Skip if not enough text to compare
    if len(task_texts) < 2 or all(not text.strip() for text in task_texts):
        print("Not enough text data for meaningful similarity analysis.")
        return
    
    # Create TF-IDF vectors
    vectorizer = TfidfVectorizer(stop_words='english', min_df=2)
    try:
        tfidf_matrix = vectorizer.fit_transform(task_texts)
    except ValueError as e:
        print(f"Error creating TF-IDF matrix: {e}")
        return
    
    # Calculate pairwise cosine similarity
    similarity_matrix = cosine_similarity(tfidf_matrix, tfidf_matrix)
    
    # Find similar task pairs
    similar_pairs = []
    for i in range(len(similarity_matrix)):
        for j in range(i + 1, len(similarity_matrix)):
            similarity = similarity_matrix[i][j]
            if similarity >= similarity_threshold:
                similar_pairs.append((i, j, similarity))
    
    # Group similar tasks
    task_groups = []
    visited = set()
    
    for i, j, sim in similar_pairs:
        if i in visited and j in visited:
            continue
            
        group = set()
        if i not in visited:
            group.add(i)
            visited.add(i)
        if j not in visited:
            group.add(j)
            visited.add(j)
            
        # Find all tasks similar to any task in the current group
        changed = True
        while changed:
            changed = False
            for x, y, s in similar_pairs:
                if (x in group or y in group) and (x not in group or y not in group):
                    group.add(x)
                    group.add(y)
                    changed = True
                    
        if group:
            task_groups.append((group, sim))
    
    # Print similarity analysis results
    if not task_groups:
        print(f"No similar task groups found with similarity >= {similarity_threshold}")
        return
    
    print(f"\nFound {len(task_groups)} groups of similar tasks (similarity >= {similarity_threshold}):")
    for group_idx, (group, avg_similarity) in enumerate(task_groups, 1):
        print(f"\nGroup {group_idx} (avg similarity: {avg_similarity:.2f}):")
        for task_idx in sorted(group):
            task = tasks[task_idx]
            print(f"  - {task['repo']} (ID: {task.get('instance_id', 'N/A')})")
            if 'problem_statement' in task and task['problem_statement']:
                print(f"    Problem: {task['problem_statement'][:150]}...")
            if 'testcases' in task and task['testcases']:
                test_cases = task['testcases']
                if isinstance(test_cases, list) and len(test_cases) > 0:
                    print(f"    Test case: {str(test_cases[0])[:100]}...")
                else:
                    print(f"    Test case: {str(test_cases)[:100]}...")

if __name__ == "__main__":
    main()
```
