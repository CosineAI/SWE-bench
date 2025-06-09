import pytest

from swebench.collect.utils import is_test_file

@pytest.mark.parametrize("path", [
    # Python
    "tests/test_example.py",
    "project/tests/test_utils.py",
    "src/testing/helpers.py",
    "src/e2e/test_full.py",
    "integration/test_api.py",
    "src/test/python/test_api.py",
    "my_package/tests/example_test.py",
    "src/test/python/FooTest.java",  # Java convention in pythonic test dir
    # Go
    "pkg/foo_test.go",
    "internal/bar/_test.go",
    "src/specs/foo_test.go",
    # Java
    "src/test/java/com/FooTest.java",
    "src/spec/java/com/FooTest.java",
    "src/specs/FooTest.java",
    # Rust
    "crates/module/tests/test_something.rs",
    "src/test.rs",
    "foo_test.rs",
    # Ruby
    "spec/foo_test.rb",
    "spec/helpers/FooTest.rb",
    "test/integration/foo_test.rb",
    # PHP
    "tests/FooTest.php",
    "src/tests/FooTest.php",
    # TypeScript/JavaScript
    "src/__tests__/foo.test.ts",
    "src/tests/foo_test.ts",
    "lib/spec/foo_test.js",
    "src/test/foo_test.js",
    # C/C++/C#
    "src/tests/foo_test.c",
    "src/tests/foo_test.cpp",
    "src/tests/FooTest.cs",
    "src/tests/FooTest.cpp",
    # Misc structure
    "src/test/helpers/helper.py",
    "testsuite/test_api.py",
    "e2e/test_api.py",
])
def test_is_test_file_positive(path):
    assert is_test_file(path) is True, f"Should detect test file: {path}"

@pytest.mark.parametrize("path", [
    # Not test files
    "src/main/app.py",
    "src/foo/bar.py",
    "src/foo/bar.go",
    "src/utils/helper.rs",
    "src/components/App.tsx",
    "src/java/com/Foo.java",
    "src/module/lib.c",
    "src/src_test/bar.py",  # tricky, but not a test dir or suffix
    "README.md",
    "docs/specification.md",
])
def test_is_test_file_negative(path):
    assert is_test_file(path) is False, f"Should not detect test file: {path}"