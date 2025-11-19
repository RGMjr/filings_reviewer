#!/usr/bin/env python3
"""
Generate a manifest of currently downloaded filings.

This helps track what fixtures we have before removing them from git.
"""

import json
from pathlib import Path

def generate_manifest():
    """Generate manifest of all fixtures in data/filings."""
    filings_dir = Path("data/filings")
    
    if not filings_dir.exists():
        print("No filings directory found")
        return
    
    manifest = []
    
    # Walk through CIK directories
    for cik_dir in sorted(filings_dir.iterdir()):
        if not cik_dir.is_dir():
            continue
            
        for accession_dir in sorted(cik_dir.iterdir()):
            if not accession_dir.is_dir():
                continue
                
            primary_htm = accession_dir / "primary.htm"
            if primary_htm.exists():
                # Extract info from path
                cik = cik_dir.name
                accession = accession_dir.name
                size = primary_htm.stat().st_size
                
                manifest.append({
                    "cik": cik,
                    "accession_number": accession,
                    "file_size": size,
                    "path": str(primary_htm.relative_to(filings_dir.parent))
                })
    
    # Save manifest
    manifest_path = Path("data/fixtures/filings_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    print(f"✓ Generated manifest with {len(manifest)} filings")
    print(f"  Saved to: {manifest_path}")
    print(f"  Total size: {sum(f['file_size'] for f in manifest) / 1024 / 1024:.1f} MB")

if __name__ == "__main__":
    generate_manifest()
