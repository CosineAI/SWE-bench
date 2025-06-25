import json
import os
from pathlib import Path
from datasets import load_dataset
from typing import Dict, List, Any, Set
from collections import defaultdict

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

def get_field_types(dataset: List[Dict[str, Any]]) -> Dict[str, Set[type]]:
    """Analyze field types across all instances in a dataset."""
    field_types = defaultdict(set)
    
    for instance in dataset:
        for key, value in instance.items():
            field_types[key].add(type(value))
    
    return dict(field_types)

def validate_field_structure(original_types: Dict[str, Set[type]], 
                           converted_types: Dict[str, Set[type]]) -> List[str]:
    """Validate that field types match between original and converted datasets."""
    issues = []
    
    # Check for missing fields
    missing_fields = set(original_types.keys()) - set(converted_types.keys())
    if missing_fields:
        issues.append(f"Missing fields in converted dataset: {missing_fields}")
    
    # Check for extra fields
    extra_fields = set(converted_types.keys()) - set(original_types.keys())
    if extra_fields:
        issues.append(f"Extra fields in converted dataset: {extra_fields}")
    
    # Check field types
    for field in original_types:
        if field in converted_types:
            orig_types = original_types[field]
            conv_types = converted_types[field]
            
            # Allow None/NoneType flexibility for optional fields
            orig_types_clean = {t for t in orig_types if t is not type(None)}
            conv_types_clean = {t for t in conv_types if t is not type(None)}
            
            if orig_types_clean != conv_types_clean:
                issues.append(f"Type mismatch for field '{field}': "
                            f"original={orig_types}, converted={conv_types}")
    
    return issues

def validate_required_fields(tasks: List[Dict[str, Any]], 
                           required_fields: Set[str]) -> List[str]:
    """Validate that all required fields are present and non-empty."""
    issues = []
    
    for i, task in enumerate(tasks):
        for field in required_fields:
            if field not in task:
                issues.append(f"Task {i}: Missing required field '{field}'")
            elif task[field] is None or (isinstance(task[field], str) and not task[field].strip()):
                issues.append(f"Task {i}: Empty required field '{field}'")
    
    return issues

def validate_list_fields(tasks: List[Dict[str, Any]], 
                        list_fields: Set[str]) -> List[str]:
    """
    Validate that specified fields are always lists.
    Note: FAIL_TO_PASS and PASS_TO_PASS are strings in the original SWE-bench dataset,
    so we'll exclude them from this validation.
    """
    issues = []
    
    # These fields are strings in the original dataset, not lists
    exclude_fields = {"FAIL_TO_PASS", "PASS_TO_PASS"}
    
    for i, task in enumerate(tasks):
        for field in list_fields:
            if field in exclude_fields:
                continue  # Skip validation for these fields
                
            if field in task and not isinstance(task[field], list):
                issues.append(f"Task {i}: Field '{field}' should be a list, got {type(task[field])}")
    
    return issues

def convert_to_swebench_format(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert tasks to SWE-bench format with proper type handling."""
    swebench_tasks = []
    
    for task in tasks:
        # Create the task with the same structure as the original SWE-bench dataset
        swebench_task = {
            "repo": task.get("repo", ""),
            "instance_id": task.get("instance_id", ""),
            "base_commit": task.get("base_commit", ""),
            "patch": task.get("patch", ""),
            "test_patch": task.get("test_patch", ""),
            "problem_statement": task.get("problem_statement", ""),
            "hints_text": task.get("hints_text", ""),
            "created_at": task.get("created_at", "2025-06-25"),
            "version": task.get("version", "2.0"),
            "FAIL_TO_PASS": task.get("FAIL_TO_PASS", ""),  # Keep as string
            "PASS_TO_PASS": task.get("PASS_TO_PASS", ""),  # Keep as string
            "environment_setup_commit": task.get("environment_setup_commit", ""),
        }
        
        swebench_tasks.append(swebench_task)
    
    return swebench_tasks

def validate_instance_ids(tasks: List[Dict[str, Any]]) -> List[str]:
    """Validate that instance IDs are unique and properly formatted."""
    issues = []
    instance_ids = set()
    
    for i, task in enumerate(tasks):
        instance_id = task.get("instance_id", "")
        
        if not instance_id:
            issues.append(f"Task {i}: Empty instance_id")
        elif instance_id in instance_ids:
            issues.append(f"Task {i}: Duplicate instance_id '{instance_id}'")
        else:
            instance_ids.add(instance_id)
        
        # Check instance_id format (should typically be repo__issue_number or similar)
        if instance_id and "__" not in instance_id:
            issues.append(f"Task {i}: Instance_id '{instance_id}' doesn't follow expected format")
    
    return issues

def main():
    # Load original SWE-bench dataset for validation
    print("Loading original SWE-bench dataset...")
    try:
        original_dataset = load_dataset("princeton-nlp/SWE-bench", split="test")
        original_list = [dict(item) for item in original_dataset]
        print(f"Original SWE-bench test set size: {len(original_list)} tasks")
        
        # Analyze original dataset structure
        original_field_types = get_field_types(original_list)
        print(f"\nOriginal dataset fields: {set(original_field_types.keys())}")
        
    except Exception as e:
        print(f"Error loading original SWE-bench dataset: {e}")
        original_dataset = None
        original_list = []
        original_field_types = {}
    
    # Load and convert tasks
    print("\nProcessing task files...")
    tasks_dir = os.path.join(os.path.dirname(__file__), "data", "tasks")
    tasks = load_tasks(tasks_dir)
    swebench_tasks = convert_to_swebench_format(tasks)
    
    print(f"\nConverted {len(swebench_tasks)} tasks to SWE-bench v2 format")
    
    # Validation checks
    print("\n" + "="*50)
    print("VALIDATION CHECKS")
    print("="*50)
    
    all_issues = []
    
    # 1. Validate field structure against original
    if original_field_types:
        converted_field_types = get_field_types(swebench_tasks)
        structure_issues = validate_field_structure(original_field_types, converted_field_types)
        all_issues.extend(structure_issues)
        
        if structure_issues:
            print("\n❌ FIELD STRUCTURE ISSUES:")
            for issue in structure_issues:
                print(f"  - {issue}")
        else:
            print("\n✅ Field structure matches original SWE-bench format")
    
    # 2. Validate required fields
    required_fields = {"repo", "instance_id", "base_commit", "patch", "problem_statement"}
    required_issues = validate_required_fields(swebench_tasks, required_fields)
    all_issues.extend(required_issues)
    
    if required_issues:
        print(f"\n❌ REQUIRED FIELD ISSUES ({len(required_issues)} total):")
        for issue in required_issues[:5]:  # Show first 5
            print(f"  - {issue}")
        if len(required_issues) > 5:
            print(f"  ... and {len(required_issues) - 5} more")
    else:
        print("\n✅ All required fields present and valid")
    
    # 3. Validate list fields
    list_fields = {"FAIL_TO_PASS", "PASS_TO_PASS", "issue_numbers"}
    list_issues = validate_list_fields(swebench_tasks, list_fields)
    all_issues.extend(list_issues)
    
    if list_issues:
        print(f"\n❌ LIST FIELD ISSUES ({len(list_issues)} total):")
        for issue in list_issues[:5]:
            print(f"  - {issue}")
        if len(list_issues) > 5:
            print(f"  ... and {len(list_issues) - 5} more")
    else:
        print("\n✅ All list fields properly formatted")
    
    # 4. Validate instance IDs
    id_issues = validate_instance_ids(swebench_tasks)
    all_issues.extend(id_issues)
    
    if id_issues:
        print(f"\n❌ INSTANCE ID ISSUES ({len(id_issues)} total):")
        for issue in id_issues[:5]:
            print(f"  - {issue}")
        if len(id_issues) > 5:
            print(f"  ... and {len(id_issues) - 5} more")
    else:
        print("\n✅ All instance IDs are unique and properly formatted")
    
    # Summary
    print("\n" + "="*50)
    if all_issues:
        print(f"❌ VALIDATION FAILED: {len(all_issues)} issues found")
        print("Please fix these issues before using as a drop-in replacement")
    else:
        print("✅ ALL VALIDATIONS PASSED")
        print("Dataset is ready to use as a drop-in replacement for SWE-bench!")
    
    # Count by repo
    repo_counts = {}
    for task in swebench_tasks:
        repo = task['repo']
        repo_counts[repo] = repo_counts.get(repo, 0) + 1
    
    print(f"\nTask counts by repository ({len(repo_counts)} repositories):")
    for repo, count in sorted(repo_counts.items()):
        print(f"  {repo}: {count} tasks")
    
    # Save the converted tasks
    output_file = os.path.join(os.path.dirname(__file__), "swebench_v2.jsonl")
    with open(output_file, 'w') as f:
        for task in swebench_tasks:
            f.write(json.dumps(task) + '\n')
    
    print(f"\nConverted tasks saved to: {output_file}")

if __name__ == "__main__":
    main()