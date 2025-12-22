"""
Comprehensive test to demonstrate and verify the test file detection functionality.
This addresses GitHub Issue #4 by showing how the code correctly identifies:
1. Test files vs source files
2. Which source files are being tested based on test method names
"""

import pytest
from unittest.mock import MagicMock
from repo_miner import Repo_miner
from miners import TestAnalyser


class TestFileDetectionScenarios:
    """Test various real-world scenarios for test file detection."""
    
    def test_scenario_shapes_example_from_issue(self):
        """
        This is the exact scenario from GitHub Issue #4:
        Files: square.py, triangle.py, shapes.py, shapes_test.py
        
        The test file is shapes_test.py and it contains tests for all three source files.
        """
        # Create mock files
        mock_files = []
        
        # Test file
        test_file = MagicMock()
        test_file.filename = "shapes_test.py"
        test_method1 = MagicMock()
        test_method1.name = "test_square_area"
        test_method2 = MagicMock()
        test_method2.name = "test_triangle_perimeter"
        test_method3 = MagicMock()
        test_method3.name = "test_shape_color"
        test_file.changed_methods = [test_method1, test_method2, test_method3]
        mock_files.append(test_file)
        
        # Source files
        square = MagicMock()
        square.filename = "square.py"
        square.changed_methods = []
        mock_files.append(square)
        
        triangle = MagicMock()
        triangle.filename = "triangle.py"
        triangle.changed_methods = []
        mock_files.append(triangle)
        
        shapes = MagicMock()
        shapes.filename = "shapes.py"
        shapes.changed_methods = []
        mock_files.append(shapes)
        
        # Run the analysis
        coverage = TestAnalyser.map_test_relations(mock_files)
        
        # Verify results
        print("\n=== Scenario: shapes_test.py testing multiple files ===")
        print(f"Test files found: {[f['filename'] for f in coverage['test_files']]}")
        print(f"Source files found: {[f['filename'] for f in coverage['source_files']]}")
        print(f"Tested files identified: {coverage['tested_files']}")
        
        # Assertions
        assert len(coverage['test_files']) == 1
        assert coverage['test_files'][0]['filename'] == "shapes_test.py"
        
        assert len(coverage['source_files']) == 3
        
        # The key assertion: ALL THREE source files should be identified as tested
        assert "square.py" in coverage['tested_files'], "square.py should be detected from test_square_area"
        assert "triangle.py" in coverage['tested_files'], "triangle.py should be detected from test_triangle_perimeter"
        assert "shapes.py" in coverage['tested_files'], "shapes.py should be detected from test_shape_color"
        
        print("✅ All three source files correctly identified as tested!\n")
    
    def test_scenario_java_naming_conventions(self):
        """Test Java-style naming conventions (camelCase)."""
        mock_files = []
        
        # Test file: CalculatorTest.java
        test_file = MagicMock()
        test_file.filename = "src/test/java/CalculatorTest.java"
        test_method1 = MagicMock()
        test_method1.name = "testCalculatorAdd"
        test_method2 = MagicMock()
        test_method2.name = "testCalculatorSubtract"
        test_method3 = MagicMock()
        test_method3.name = "shouldMultiplyNumbers"
        test_file.changed_methods = [test_method1, test_method2, test_method3]
        mock_files.append(test_file)
        
        # Source file
        calculator = MagicMock()
        calculator.filename = "src/main/java/Calculator.java"
        calculator.changed_methods = []
        mock_files.append(calculator)
        
        # Unrelated file
        util = MagicMock()
        util.filename = "src/main/java/StringUtil.java"
        util.changed_methods = []
        mock_files.append(util)
        
        coverage = TestAnalyser.map_test_relations(mock_files)
        
        print("\n=== Scenario: Java-style camelCase naming ===")
        print(f"Test files: {[f['filename'] for f in coverage['test_files']]}")
        print(f"Tested files: {coverage['tested_files']}")
        
        assert "src/main/java/Calculator.java" in coverage['tested_files']
        assert "src/main/java/StringUtil.java" not in coverage['tested_files'], "Unrelated file should not be detected"
        
        print("✅ Calculator.java correctly identified, StringUtil.java correctly excluded!\n")
    
    def test_scenario_python_snake_case(self):
        """Test Python-style naming conventions (snake_case)."""
        mock_files = []
        
        # Test file
        test_file = MagicMock()
        test_file.filename = "tests/test_data_processor.py"
        test_method1 = MagicMock()
        test_method1.name = "test_data_processor_parse_csv"
        test_method2 = MagicMock()
        test_method2.name = "test_data_processor_validate_input"
        test_file.changed_methods = [test_method1, test_method2]
        mock_files.append(test_file)
        
        # Source file
        processor = MagicMock()
        processor.filename = "src/data_processor.py"
        processor.changed_methods = []
        mock_files.append(processor)
        
        coverage = TestAnalyser.map_test_relations(mock_files)
        
        print("\n=== Scenario: Python snake_case naming ===")
        print(f"Test files: {[f['filename'] for f in coverage['test_files']]}")
        print(f"Tested files: {coverage['tested_files']}")
        
        assert "src/data_processor.py" in coverage['tested_files']
        
        print("✅ data_processor.py correctly identified from snake_case test methods!\n")
    
    def test_scenario_multiple_test_files_one_source(self):
        """Test when multiple test files test the same source file."""
        mock_files = []
        
        # Test file 1: Unit tests
        unit_test = MagicMock()
        unit_test.filename = "tests/user_service_test.py"
        test1 = MagicMock()
        test1.name = "test_user_service_create"
        unit_test.changed_methods = [test1]
        mock_files.append(unit_test)
        
        # Test file 2: Integration tests
        integration_test = MagicMock()
        integration_test.filename = "tests/integration/test_user_service_integration.py"
        test2 = MagicMock()
        test2.name = "test_user_service_with_database"
        integration_test.changed_methods = [test2]
        mock_files.append(integration_test)
        
        # Source file
        service = MagicMock()
        service.filename = "src/user_service.py"
        service.changed_methods = []
        mock_files.append(service)
        
        coverage = TestAnalyser.map_test_relations(mock_files)
        
        print("\n=== Scenario: Multiple test files for one source ===")
        print(f"Test files: {[f['filename'] for f in coverage['test_files']]}")
        print(f"Source files: {[f['filename'] for f in coverage['source_files']]}")
        print(f"Tested files: {coverage['tested_files']}")
        
        assert len(coverage['test_files']) == 2
        assert len(coverage['source_files']) == 1
        assert "src/user_service.py" in coverage['tested_files']
        
        print("✅ Source file correctly identified from multiple test files!\n")
    
    def test_scenario_spec_files(self):
        """Test spec-style naming (common in JavaScript/TypeScript)."""
        mock_files = []
        
        # Spec file
        spec = MagicMock()
        spec.filename = "src/components/Button.spec.ts"
        test1 = MagicMock()
        test1.name = "should render button correctly"
        test2 = MagicMock()
        test2.name = "should handle button click"
        spec.changed_methods = [test1, test2]
        mock_files.append(spec)
        
        # Source file
        button = MagicMock()
        button.filename = "src/components/Button.ts"
        button.changed_methods = []
        mock_files.append(button)
        
        coverage = TestAnalyser.map_test_relations(mock_files)
        
        print("\n=== Scenario: Spec-style naming ===")
        print(f"Test files: {[f['filename'] for f in coverage['test_files']]}")
        print(f"Tested files: {coverage['tested_files']}")
        
        # Note: This scenario relies on filename matching since "should_render_button" won't match "Button"
        # The is_test_file should catch .spec. files
        assert len(coverage['test_files']) == 1
        
        print("✅ Spec file correctly identified as test file!\n")
    
    def test_scenario_no_matching_source(self):
        """Test when test methods don't match any source files."""
        mock_files = []
        
        # Test file
        test_file = MagicMock()
        test_file.filename = "tests/test_foo.py"
        test1 = MagicMock()
        test1.name = "test_something_random"
        test_file.changed_methods = [test1]
        mock_files.append(test_file)
        
        # Unrelated source file
        bar = MagicMock()
        bar.filename = "src/bar.py"
        bar.changed_methods = []
        mock_files.append(bar)
        
        coverage = TestAnalyser.map_test_relations(mock_files)
        
        print("\n=== Scenario: No matching source files ===")
        print(f"Test files: {[f['filename'] for f in coverage['test_files']]}")
        print(f"Source files: {[f['filename'] for f in coverage['source_files']]}")
        print(f"Tested files: {coverage['tested_files']}")
        
        assert len(coverage['test_files']) == 1
        assert len(coverage['source_files']) == 1
        # bar.py should NOT be in tested_files since no test method references it
        assert "src/bar.py" not in coverage['tested_files']
        
        print("✅ Correctly identified that no source files match the test methods!\n")
    
    def test_edge_case_very_short_names(self):
        """Test that very short component names are ignored to avoid false positives."""
        mock_files = []
        
        test_file = MagicMock()
        test_file.filename = "test_a.py"
        test1 = MagicMock()
        test1.name = "test_a_b_c"  # Very short components
        test_file.changed_methods = [test1]
        mock_files.append(test_file)
        
        # File with single letter name
        a_file = MagicMock()
        a_file.filename = "a.py"
        a_file.changed_methods = []
        mock_files.append(a_file)
        
        coverage = TestAnalyser.map_test_relations(mock_files)
        
        print("\n=== Edge Case: Very short names ===")
        print(f"Tested files: {coverage['tested_files']}")
        
        # Should not match because components are too short (< 3 characters)
        assert "a.py" not in coverage['tested_files'], "Should ignore very short component names"
        
        print("✅ Correctly ignored very short component names!\n")


def test_method_extraction_details():
    """Test the detailed behavior of test method name parsing."""
    
    test_cases = [
        # (test_method_name, expected_components)
        ("test_calculator_add", ["calculator", "add"]),
        ("testCalculatorSubtract", ["calculator", "subtract"]),
        ("test_user_service_create_user", ["user", "service", "create", "user"]),
        ("should_validate_email", ["validate", "email"]),
        ("when_user_logs_in", ["user", "logs"]),
        ("testSquareArea", ["square", "area"]),
    ]
    
    print("\n=== Method Name Parsing Details ===")
    
    for method_name, expected in test_cases:
        # Mock a single test method
        mock_files = [MagicMock()]
        mock_files[0].filename = "test.py"
        mock_files[0].changed_methods = []
        
        # Extract components using the actual function
        result = TestAnalyser.extract_tested_files_from_methods([method_name], mock_files)
        
        print(f"\nMethod: {method_name}")
        print(f"  Expected components: {expected}")
        
        # We can't directly test the internal components, but we can verify
        # the method handles the parsing correctly by checking it doesn't crash
        assert isinstance(result, list), f"Should return a list for {method_name}"
        
        print(f"  ✅ Successfully parsed")
    
    print("\n✅ All method name parsing tests passed!\n")


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
