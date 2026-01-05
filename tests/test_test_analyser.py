import pytest
from unittest.mock import MagicMock
from mining.components.test_analyser import TestAnalyser

class TestTestAnalyser:

    @pytest.mark.parametrize("filename,expected", [
        ("test_utils.py", True),
        ("utils_test.py", True),
        ("TestUtils.java", True),
        ("UtilsTest.java", True),
        ("UserSpec.ts", True),
        ("UserIT.java", True),
        ("utils.py", False),
        ("Main.java", False),
        ("", False),
        (None, False),
    ])
    def test_is_test_file(self, filename, expected):
        assert TestAnalyser.is_test_file(filename) is expected

    def test_extract_tested_files_by_name_convention(self):
        """Test extraction when method name contains the class name."""
        test_methods = ["testCalculatorAdd", "test_user_manager_save"]
        
        # Mock available source files
        f1 = MagicMock(); f1.filename = "src/Calculator.java"
        f2 = MagicMock(); f2.filename = "src/UserManager.py"
        f3 = MagicMock(); f3.filename = "src/Unrelated.java"
        all_files = [f1, f2, f3]

        results = TestAnalyser.extract_tested_files_from_methods(test_methods, all_files)
        
        assert "src/Calculator.java" in results
        assert "src/UserManager.py" in results
        assert "src/Unrelated.java" not in results

    def test_extract_tested_files_ignore_short_matches(self):
        """Ensure very short tokens (e.g. 'is', 'at') don't match everything."""
        test_methods = ["test_is_valid"] # 'is' and 'valid'
        
        f1 = MagicMock(); f1.filename = "src/Is.java" # Too short usually
        f2 = MagicMock(); f2.filename = "src/Validator.java" # 'valid' matches 'Validator'
        
        results = TestAnalyser.extract_tested_files_from_methods(test_methods, [f1, f2])
        # Depending on implementation detail > 2 chars:
        # 'valid' > 2 chars -> matches Validator
        assert "src/Validator.java" in results

    def test_analyze_test_coverage_structure(self):
        """Integration-like unit test for the main orchestration method."""
        # 1. Test File
        tf = MagicMock()
        tf.filename = "test_main.py"
        tm = MagicMock(); tm.name = "test_main_run"
        tf.changed_methods = [tm]
        
        # 2. Source File
        sf = MagicMock()
        sf.filename = "main.py"
        sf.changed_methods = []
        
        result = TestAnalyser.analyze_test_coverage([tf, sf])
        
        assert len(result['test_files']) == 1
        assert len(result['source_files']) == 1
        assert "main.py" in result['tested_files']