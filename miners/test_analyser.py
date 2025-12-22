"""
Test analysis utilities for detecting test files and identifying tested source files.
"""

import os
import re


class TestAnalyser:
    """Utilities for analysing test files and coverage."""
    
    @staticmethod
    def is_test_file(filename):
        """
        Determines if a file is a test file based on naming conventions.
        
        Args:
            filename (str): The name of the file to check.
            
        Returns:
            bool: True if the file is a test file, False otherwise.
        """
        if not filename:
            return False
        
        # Split extension to check the base name
        base_name, _ = os.path.splitext(os.path.basename(filename))
        lower_filename = base_name.lower()

        # Categorise test file naming conventions as prefixes or suffixes
        prefixes = ( 'test_', 'tests_')
        suffixes = ('test', 'tests', '_test', '_tests', 'spec', '_spec')
        
        # Check for the test prefixes or suffixes in the filename
        if lower_filename.startswith(prefixes) or lower_filename.endswith(suffixes):
            return True
        
        # Check Case-Sensitive 'IT (Integration Test)' Patterns
        if base_name.endswith('IT'):
            return True

        return False
    
    @staticmethod
    def extract_tested_files_from_methods(test_methods, all_files):
        """
        Identifies which source files are being tested based on test method names.
        
        This function analyses test method names to extract the class/module names
        being tested, then matches them against the list of modified files.
        
        Common patterns recognized:
        - testMethodName / test_method_name
        - TestClassName / test_class_name
        - Method names containing the tested class name
        
        Args:
            test_methods (list): List of test method names.
            all_files (list): List of all file objects in the commit.
            
        Returns:
            list: List of filenames that are likely being tested.
        """
        if not test_methods or not all_files:
            return []
        
        tested_files = set()
        
        # Extract potential class/module names from test methods
        # Example: testCalculatorAdd -> Calculator
        # Example: test_square_area -> square
        tested_components = set()
        
        for method_name in test_methods:
            if not method_name:
                continue
            
            method_lower = method_name.lower()
            
            # Remove common test prefixes/suffixes
            cleaned = method_lower
            for prefix in ['test_', 'test', 'should_', 'should', 'when_', 'when']:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):]
                    break
            
            for suffix in ['_test', 'test', '_spec', 'spec']:
                if cleaned.endswith(suffix):
                    cleaned = cleaned[:-len(suffix)]
                    break
            
            # Split by underscores or camelCase to extract component names
            # Example: calculate_area -> ['calculate', 'area']
            parts = cleaned.split('_')
            tested_components.update(parts)
            
            # Also handle camelCase: calculateArea -> ['calculate', 'Area']
            camel_parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', method_name)
            tested_components.update([p.lower() for p in camel_parts if len(p) > 2])
        
        # Match extracted components against source files
        for file_obj in all_files:
            if not file_obj.filename:
                continue
            
            # Skip test files themselves
            if TestAnalyser.is_test_file(file_obj.filename):
                continue
            
            # Extract base filename without path and extension
            base_filename = os.path.basename(file_obj.filename)
            filename_without_ext = os.path.splitext(base_filename)[0].lower()
            
            # Check if any tested component matches this filename
            for component in tested_components:
                if component and len(component) > 2:  # Ignore very short matches
                    if component in filename_without_ext or filename_without_ext in component:
                        tested_files.add(file_obj.filename)
                        break
        
        return list(tested_files)
    
    @staticmethod
    def map_test_relations(modified_files):
        """
        Analyzes a commit to determine which files are tests and which are being tested.
        
        Args:
            modified_files (list): List of ModifiedFile objects from a commit.
            
        Returns:
            dict: A dictionary containing:
                - 'test_files': List of test file information
                - 'source_files': List of source file information
                - 'tested_files': List of source files that have associated tests
        """
        from .file_analyser import FileAnalyser
        
        test_files = []
        source_files = []
        all_test_methods = []
        
        # First pass: categorize files and collect test methods
        for f in modified_files:
            if not f.filename:
                continue
            
            file_info = {
                'filename': f.filename,
                'changed_methods': [m.name for m in f.changed_methods] if f.changed_methods else []
            }
            
            if TestAnalyser.is_test_file(f.filename):
                test_files.append(file_info)
                all_test_methods.extend(file_info['changed_methods'])
            else:
                source_files.append(file_info)
        
        # Second pass: identify which source files are being tested
        tested_files = TestAnalyser.extract_tested_files_from_methods(
            all_test_methods,
            modified_files
        )
        
        return {
            'test_files': test_files,
            'source_files': source_files,
            'tested_files': tested_files
        }
