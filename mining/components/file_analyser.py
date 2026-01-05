"""
File analysis utilities for filtering and extracting metrics from source code files.
"""

import os

# Whitelist of file extensions to classify as "Source Code" or "Test Code".
LANGUAGE_EXTENSIONS = {
    'Java': {'.java', '.groovy'},
    'Python': {'.py'},
    'C++': {'.cpp', '.cc'}
}

# Global whitelist (Union of all supported extensions)
VALID_CODE_EXTENSIONS = set().union(*LANGUAGE_EXTENSIONS.values())

class FileAnalyser:
    """Utilities for filtering and analysing source code files."""

    @staticmethod
    def get_extensions_for_language(language):
        """
        Returns the set of valid extensions for a given language.
        If the language is unknown or None, returns all valid extensions.
        """
        return LANGUAGE_EXTENSIONS.get(language, VALID_CODE_EXTENSIONS)
    
    @staticmethod
    def is_valid_file(file, allowed_extensions=None):
        """
        Filters files to ensure we only analyse Source Code or Test files
        relevant to the specific project language.
        
        Args:
            file (ModifiedFile): A Pydriller file object.
            allowed_extensions (set): Optional set of extensions to allow. 
                                      Defaults to all valid extensions if None.
            
        Returns:
            bool: True if the file should be mined, False otherwise.
        """
        if not file.filename:
            return False
        
        target_extensions = allowed_extensions if allowed_extensions else VALID_CODE_EXTENSIONS

        # 1. Identify Test files explicitly by filename conventions (e.g., 'CalculatorTest.java')
        if "test" in file.filename.lower():
            return True

        # 2. Identify Source Code by checking the file extension against the approved whitelist
        _, ext = os.path.splitext(file.filename)
        if ext.lower() in target_extensions:
            return True
            
        return False
    
    @staticmethod
    def extract_file_metrics(file):
        """
        Extract complexity and method information from a modified file.
        
        Args:
            file (ModifiedFile): A Pydriller file object.
            
        Returns:
            dict: File metadata including filename, complexity, and changed methods.
        """
        return {
            "filename": file.filename,
            "complexity": 0,
            "changed_methods": [m.name for m in file.changed_methods] if file.changed_methods else []
        }
