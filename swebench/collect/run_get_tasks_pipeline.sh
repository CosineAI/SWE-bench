#!/usr/bin/env bash

# If you'd like to parallelize, do the following:
# * Create a .env file in this folder
# * Declare GITHUB_TOKENS=token1,token2,token3...

# To use multi-language support (e.g., Python, JavaScript, Ruby), add:
#   --languages 'python,javascript,ruby'
# Example:
# python get_tasks_pipeline.py \
#     --repos 'OWNER1/REPO1', 'OWNER2/REPO2' \
#     --path_prs '<path to folder to save PRs to>' \
#     --path_tasks '<path to folder to save tasks to>' \
#     --languages 'python,javascript,ruby'

python get_tasks_pipeline.py \
    --repos 'scikit-learn/scikit-learn', 'pallets/flask' \
    --path_prs '<path to folder to save PRs to>' \
    --path_tasks '<path to folder to save tasks to>'