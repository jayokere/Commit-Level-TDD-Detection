"""
Miners package: Modular components for repository analysis.

Exports:
- FileAnalyser: File filtering, validation, complexity extraction
- TestAnalyser: Test detection and coverage analysis
- CommitProcessor: Core commit traversal and metric extraction
"""

from .file_analyser import FileAnalyser
from .test_analyser import TestAnalyser
from .commit_processor import CommitProcessor

__all__ = ["FileAnalyser", "TestAnalyser", "CommitProcessor"]
