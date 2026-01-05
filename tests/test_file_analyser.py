import pytest
from unittest.mock import MagicMock
from mining.components.file_analyser import FileAnalyser, VALID_CODE_EXTENSIONS

class TestFileAnalyser:
    
    def test_valid_code_extensions(self):
        """Ensure specific extensions are in the whitelist."""
        assert '.java' in VALID_CODE_EXTENSIONS
        assert '.py' in VALID_CODE_EXTENSIONS
        assert '.cpp' in VALID_CODE_EXTENSIONS

    def test_is_valid_file_valid_extension(self):
        mock_file = MagicMock()
        mock_file.filename = "src/main.py"
        assert FileAnalyser.is_valid_file(mock_file) is True

    def test_is_valid_file_test_in_name(self):
        mock_file = MagicMock()
        # Even if extension wasn't valid (though .java is), 'Test' in name makes it valid
        mock_file.filename = "CalculatorTest.unknown"
        assert FileAnalyser.is_valid_file(mock_file) is True

    def test_is_valid_file_invalid(self):
        mock_file = MagicMock()
        mock_file.filename = "readme.md"
        assert FileAnalyser.is_valid_file(mock_file) is False

    def test_is_valid_file_none_filename(self):
        mock_file = MagicMock()
        mock_file.filename = None
        assert FileAnalyser.is_valid_file(mock_file) is False

    def test_extract_file_metrics(self):
        mock_file = MagicMock()
        mock_file.filename = "script.py"
        # Mock changed_methods
        m1 = MagicMock(); m1.name = "func1"
        m2 = MagicMock(); m2.name = "func2"
        mock_file.changed_methods = [m1, m2]
        
        metrics = FileAnalyser.extract_file_metrics(mock_file)
        
        assert metrics['filename'] == "script.py"
        assert metrics['complexity'] == 0
        assert metrics['changed_methods'] == ["func1", "func2"]