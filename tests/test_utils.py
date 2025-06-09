import pytest
from swebench.collect.utils import _is_test_path

@pytest.mark.parametrize(
    "path,expected",
    [
        # True cases
        ("src/foo/bar_test.go", True),
        ("lib/foo.spec.ts", True),
        ("tests/unit/test_math.py", True),
        ("some/path/IntegrationTest.java", True),
        ("src/components/Button.test.jsx", True),
        ("src/components/Button.spec.tsx", True),
        ("src/endtoend/e2e_login.js", True),
        ("src/unittest/unit_widget.c", True),
        ("src/unit_test/my_unit_test.cpp", True),
        ("src/specs/foo_spec.rb", True),
        ("test/test_utils.py", True),
        ("src/tests/test_utils.rs", True),
        ("src/e2e/test_e2e_case.js", True),
        # False cases
        ("src/main/java/App.java", False),
        ("docs/testing_guide.md", False),
        ("README.md", False),
        ("src/foo/bar.go", False),
        ("lib/foo.ts", False),
        ("src/production/integration_helpers.py", True),  # integration in path
        ("src/documentation/integration_guide.md", False),
        ("src/foo/tester.py", True),  # 'test' in filename
        ("src/foo/testing.py", True),  # 'testing' in filename
        ("src/foo/testify.py", True),  # 'test' in filename
        ("src/docs/unittesting.md", False),  # 'unittesting' in doc file
    ],
)
def test_is_test_path(path, expected):
    assert _is_test_path(path) == expected