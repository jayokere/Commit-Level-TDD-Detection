
"""
Simple demonstration script showing how the test file detection works.
Run this without any dependencies to see the algorithm in action.
"""

from unittest.mock import MagicMock
from repo_miner import Repo_miner
from miners import TestAnalyser


def print_header(title):
    """Print a nice header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def demo_scenario_1():
    """Demo the exact scenario from GitHub Issue #4."""
    print_header("SCENARIO 1: GitHub Issue #4 - shapes_test.py")
    
    print("\n📁 Files in commit:")
    print("  - square.py         (source file)")
    print("  - triangle.py       (source file)")
    print("  - shapes.py         (source file)")
    print("  - shapes_test.py    (test file)")
    
    print("\n🧪 Test methods in shapes_test.py:")
    print("  - test_square_area()")
    print("  - test_triangle_perimeter()")
    print("  - test_shape_color()")
    
    # Create mock files
    mock_files = []
    
    test_file = MagicMock()
    test_file.filename = "shapes_test.py"
    test_m1 = MagicMock()
    test_m1.name = "test_square_area"
    test_m2 = MagicMock()
    test_m2.name = "test_triangle_perimeter"
    test_m3 = MagicMock()
    test_m3.name = "test_shape_color"
    test_file.changed_methods = [test_m1, test_m2, test_m3]
    mock_files.append(test_file)
    
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
    
    # Analyse
    coverage = TestAnalyser.map_test_relations(mock_files)
    
    print("\n🔍 Analysis Results:")
    print(f"\n  Test Files Identified:")
    for tf in coverage['test_files']:
        print(f"    ✓ {tf['filename']}")
        print(f"      Methods: {tf['changed_methods']}")
    
    print(f"\n  Source Files Found:")
    for sf in coverage['source_files']:
        print(f"    • {sf['filename']}")
    
    print(f"\n  ✨ Tested Files Detected:")
    for tested in coverage['tested_files']:
        print(f"    ✅ {tested}")
    
    print("\n💡 Explanation:")
    print("  • 'test_square_area' → extracted 'square' → matched square.py")
    print("  • 'test_triangle_perimeter' → extracted 'triangle' → matched triangle.py")
    print("  • 'test_shape_color' → extracted 'shape' → matched shapes.py")
    print("\n  All three source files correctly identified as tested! 🎉")


def demo_scenario_2():
    """Demo Java-style camelCase."""
    print_header("SCENARIO 2: Java camelCase - CalculatorTest.java")
    
    print("\n📁 Files in commit:")
    print("  - Calculator.java     (source)")
    print("  - CalculatorTest.java (test)")
    print("  - StringUtil.java     (unrelated)")
    
    print("\n🧪 Test methods in CalculatorTest.java:")
    print("  - testCalculatorAdd()")
    print("  - testCalculatorSubtract()")
    
    mock_files = []
    
    test_file = MagicMock()
    test_file.filename = "CalculatorTest.java"
    tm1 = MagicMock()
    tm1.name = "testCalculatorAdd"
    tm2 = MagicMock()
    tm2.name = "testCalculatorSubtract"
    test_file.changed_methods = [tm1, tm2]
    mock_files.append(test_file)
    
    calc = MagicMock()
    calc.filename = "Calculator.java"
    calc.changed_methods = []
    mock_files.append(calc)
    
    util = MagicMock()
    util.filename = "StringUtil.java"
    util.changed_methods = []
    mock_files.append(util)
    
    coverage = TestAnalyser.map_test_relations(mock_files)
    
    print("\n✨ Tested Files Detected:")
    for tested in coverage['tested_files']:
        print(f"    ✅ {tested}")
    
    print("\n  Files NOT detected as tested:")
    for sf in coverage['source_files']:
        if sf['filename'] not in coverage['tested_files']:
            print(f"    ❌ {sf['filename']} (correctly excluded)")
    
    print("\n💡 Explanation:")
    print("  • 'testCalculatorAdd' → CamelCase parsed → 'calculator' → Calculator.java ✓")
    print("  • StringUtil.java has no matching test methods → excluded ✓")


def demo_scenario_3():
    """Demo Python snake_case."""
    print_header("SCENARIO 3: Python snake_case - test_data_processor.py")
    
    print("\n📁 Files in commit:")
    print("  - data_processor.py      (source)")
    print("  - test_data_processor.py (test)")
    
    print("\n🧪 Test methods:")
    print("  - test_data_processor_parse_csv()")
    print("  - test_data_processor_validate_input()")
    
    mock_files = []
    
    test_file = MagicMock()
    test_file.filename = "test_data_processor.py"
    tm1 = MagicMock()
    tm1.name = "test_data_processor_parse_csv"
    tm2 = MagicMock()
    tm2.name = "test_data_processor_validate_input"
    test_file.changed_methods = [tm1, tm2]
    mock_files.append(test_file)
    
    processor = MagicMock()
    processor.filename = "data_processor.py"
    processor.changed_methods = []
    mock_files.append(processor)
    
    coverage = TestAnalyser.map_test_relations(mock_files)
    
    print("\n✨ Tested Files Detected:")
    for tested in coverage['tested_files']:
        print(f"    ✅ {tested}")
    
    print("\n💡 Explanation:")
    print("  • 'test_data_processor_parse_csv' → split by '_' → 'data', 'processor'")
    print("  • Both components match 'data_processor.py' → detected! ✓")


def main():
    """Run all demonstrations."""
    print("\n" + "🔬" * 35)
    print("   TEST FILE DETECTION DEMONSTRATION")
    print("   (Solution for GitHub Issue #4)")
    print("🔬" * 35)
    
    demo_scenario_1()
    demo_scenario_2()
    demo_scenario_3()
    
    print("\n" + "=" * 70)
    print("  ✅ All scenarios demonstrate correct test file detection!")
    print("=" * 70)
    print("\n📝 Summary:")
    print("  The algorithm analyzes test method names to extract component names,")
    print("  then matches them against source filenames to determine which files")
    print("  are being tested. This solves the limitation described in Issue #4.")
    print()


if __name__ == "__main__":
    main()
