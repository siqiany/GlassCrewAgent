#!/usr/bin/env python3
"""
Test script for PDF reading tools.
This file tests the three PDF reading functionalities: list_downloaded_pdfs, read_local_pdf, and read_all_downloaded_pdfs.
"""

import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from GlassCrewAgent.tools.generalCommon import (
    list_downloaded_pdfs,
    read_local_pdf,
    read_all_downloaded_pdfs
)


def test_list_downloaded_pdfs():
    """Test listing available PDFs"""
    print("=" * 60)
    print("Test 1: list_downloaded_pdfs()")
    print("-" * 60)
    
    result = list_downloaded_pdfs.func()
    print(result)
    print()
    
    return "Available Downloaded PDF Files" in result


def test_read_local_pdf():
    """Test reading a single local PDF"""
    print("=" * 60)
    print("Test 2: read_local_pdf('0704.0572v1.pdf')")
    print("-" * 60)
    
    result = read_local_pdf.func('0704.0572v1.pdf')
    
    # Check basic properties
    print(f"Total characters in result: {len(result)}")
    print(f"\nFirst 500 characters:\n{result[:500]}")
    print("..." if len(result) > 500 else "")
    print()
    
    return "### PDF Content: 0704.0572v1.pdf" in result and "**Pages:** 7" in result


def test_read_all_downloaded_pdfs():
    """Test reading all downloaded PDFs"""
    print("=" * 60)
    print("Test 3: read_all_downloaded_pdfs()")
    print("-" * 60)
    
    result = read_all_downloaded_pdfs.func()
    
    print(f"Total characters in combined result: {len(result)}")
    print(f"\nFirst 500 characters:\n{result[:500]}")
    print("..." if len(result) > 500 else "")
    print()
    
    return "# Combined Content of All Downloaded PDFs" in result


def test_read_local_pdf_with_error():
    """Test error handling for non-existent PDF"""
    print("=" * 60)
    print("Test 4: read_local_pdf (non-existent file)")
    print("-" * 60)
    
    result = read_local_pdf.func('non_existent_file.pdf')
    print(result)
    print()
    
    return "Error: File" in result and "does not exist" in result


def test_read_root_pdf():
    """Test reading the siesta-5.4.2.pdf in root directory"""
    print("=" * 60)
    print("Test 5: read_local_pdf('siesta-5.4.2.pdf', '.')")
    print("-" * 60)
    
    result = read_local_pdf.func('siesta-5.4.2.pdf', '.')
    
    print(f"Total characters in result: {len(result)}")
    print(f"\nFirst 300 characters:\n{result[:300]}")
    print("..." if len(result) > 300 else "")
    print()
    
    return "### PDF Content: siesta-5.4.2.pdf" in result


def main():
    """Run all tests"""
    print("\n📄 Starting PDF Reader Tools Tests\n")
    
    tests = [
        ("List downloaded PDFs", test_list_downloaded_pdfs),
        ("Read local PDF", test_read_local_pdf),
        ("Read all downloaded PDFs", test_read_all_downloaded_pdfs),
        ("Error handling - non-existent file", test_read_local_pdf_with_error),
        ("Read PDF from different directory", test_read_root_pdf),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name}: PASSED\n")
            else:
                failed += 1
                print(f"❌ {test_name}: FAILED\n")
        except Exception as e:
            failed += 1
            print(f"❌ {test_name}: ERROR - {str(e)}\n")
    
    print("=" * 60)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n🎉 All tests passed! PDF reading tools are working correctly.")
        return 0
    else:
        print("\n⚠️  Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())