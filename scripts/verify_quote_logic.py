
import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.extraction.value_extractor import verify_quote_in_source, _normalize_text

def test_case(name, source, quote, expected=True):
    print(f"\n--- Test Case: {name} ---")
    print(f"Source:   {source!r}")
    print(f"Quote:    {quote!r}")
    
    # Show normalization
    norm_source = _normalize_text(source)
    norm_quote = _normalize_text(quote)
    print(f"Norm Src: {norm_source!r}")
    print(f"Norm Qt:  {norm_quote!r}")
    
    result = verify_quote_in_source(quote, source, threshold=0.7)
    print(f"Result:   {'PASS' if result else 'FAIL'} (Expected: {'PASS' if expected else 'FAIL'})")
    
    if result != expected:
        print("❌ UNEXPECTED RESULT")
    else:
        print("✅ OK")

def main():
    print("Verifying Quote Verifiction Improvements...")
    
    # Case 1: Punctuation differences (Dashes vs Spaces)
    test_case(
        "Punctuation: Dashes",
        "Net Dollar Retention Rate was 140%",
        "Net-Dollar Retention Rate was 140%"
    )
    
    # Case 2: Extra whitespace
    test_case(
        "Whitespace",
        "Revenue was $1.5 million",
        "Revenue  was $1.5 million"
    )
    
    # Case 3: Percent sign presence
    test_case(
        "Preserve Context: Percent",
        "Growth was 50%",
        "Growth was 50", # Should NOT match ideally if we want context, but fuzzy match might still pass. 
                         # However, let's test that the % is kept in normalization.
        expected=True # With 0.7 threshold this will likely still pass, but let's see normalization.
    )

    # Case 4: Text vs Number confusion (Old normalization might have stripped $)
    test_case(
        "Preserve Context: Currency",
        "Revenue: $15m",
        "Revenue: 15m", 
        expected=True # Again, fuzzy match will pass, but normalization should show $ kept.
    )

    # Case 5: Real failure example (if I can recall one)
    # "Net Dollar Retention Rate was 171% as of January 31, 2017"
    test_case(
        "Real Failure Example",
        "Net Dollar Retention Rate was 171% as of January 31, 2017",
        "Net Dollar Retention Rate was 171% as of January 31, 2017." # Trailing dot
    )

if __name__ == "__main__":
    main()
