#!/usr/bin/env bash

# If you'd like to parallelize, do the following:
# * Create a .env file in this folder
# * Declare GITHUB_TOKENS=token1,token2,token3...

python get_tasks_pipeline.py \
    --repos 'scikit-learn/scikit-learn', 'pallets/flask' \
    --path_prs '<path to folder to save PRs to>' \
    --path_tasks '<path to folder to save tasks to>'

# Example: collect top repositories by language (Python, JavaScript, Go)
# python get_tasks_pipeline.py \
#     --languages python javascript go \
#     --max_repos_per_language 30 \
#     --path_prs '<path to folder to save PRs to>' \
#     --path_tasks '<path to folder to save tasks to>'

# Example with recency filtering: only include repos updated in last 6 months
# python get_tasks_pipeline.py \
#     --languages python \
#     --max_repos_per_language 10 \
#     --recency_months 6 \
#     --path_prs '<path to folder to save PRs to>' \
#     --path_tasks '<path to folder to save tasks to>'