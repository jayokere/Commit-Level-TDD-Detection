"""
File analysis utilities for filtering and extracting metrics from source code files.
"""

import os

# Whitelist of file extensions to classify as "Source Code" or "Test Code".
VALID_CODE_EXTENSIONS = {
    '.java', '.py', '.cpp', '.cc', 'groovy'
}


class FileAnalyser:
    """Utilities for filtering and analysing source code files."""
    
    @staticmethod
    def is_valid_file(file):
        """
        Filters files to ensure we only analyse Source Code or Test files.
        
        Args:
            file (ModifiedFile): A Pydriller file object.
            
        Returns:
            bool: True if the file should be mined, False otherwise.
        """
        if not file.filename:
            return False
        
        # 1. Identify Test files explicitly by filename conventions (e.g., 'CalculatorTest.java')
        if "test" in file.filename.lower():
            return True

        # 2. Identify Source Code by checking the file extension against the approved whitelist
        _, ext = os.path.splitext(file.filename)
        if ext.lower() in VALID_CODE_EXTENSIONS:
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
