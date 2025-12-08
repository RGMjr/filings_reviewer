#!/usr/bin/env python3
"""
Test script for OpenAI client.

This script tests the LLM client with a simple prompt to verify:
1. API connection works
2. Token counting works
3. Cost tracking works
4. Error handling works
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.openai_client import OpenAIClient
from src.llm.prompts import PromptTemplates

def test_basic_completion():
    """Test basic LLM completion."""
    print("=" * 80)
    print("Testing OpenAI Client with GPT-4o-mini")
    print("=" * 80)
    print()

    # Initialize client
    print("1. Initializing OpenAI client...")
    try:
        client = OpenAIClient(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=500,
        )
        print("   ✓ Client initialized successfully")
        print(f"   Model: {client.model}")
        print(f"   Temperature: {client.temperature}")
        print()
    except Exception as e:
        print(f"   ✗ Failed to initialize client: {e}")
        print()
        print("   Make sure OPENAI_API_KEY is set in your environment:")
        print("   export OPENAI_API_KEY='your-api-key-here'")
        return False

    # Test simple prompt
    print("2. Testing simple completion...")
    test_prompt = "What is 2+2? Reply with just the number."

    try:
        response = client.complete(test_prompt)
        print(f"   ✓ Response: {response.content.strip()}")
        print(f"   Input tokens: {response.input_tokens}")
        print(f"   Output tokens: {response.output_tokens}")
        print(f"   Cost: ${response.cost:.6f}")
        print(f"   Latency: {response.latency_ms}ms")
        print()
    except Exception as e:
        print(f"   ✗ Failed to get response: {e}")
        return False

    # Test with longer prompt (metric extraction)
    print("3. Testing metric extraction prompt...")

    sample_text = """
    As of December 31, 2023, we had 125 million monthly active users,
    representing a 25% increase from 100 million users in the prior year.

    We define monthly active users (MAU) as users who have logged into
    our platform at least once during a calendar month.
    """

    prompt = PromptTemplates.value_extraction_from_text(
        segment_text=sample_text,
        metric_names="monthly_active_users, customer_count"
    )

    try:
        response = client.complete(
            prompt,
            system_message=PromptTemplates.SYSTEM_VALUE_EXTRACTION
        )

        print(f"   ✓ Response received ({response.output_tokens} tokens)")
        print(f"   Cost: ${response.cost:.6f}")
        print()
        print("   Extracted data:")
        print("   " + "-" * 76)

        # Try to parse JSON
        try:
            data = PromptTemplates.parse_json_response(response.content)
            if PromptTemplates.validate_value_extraction_response(data):
                for item in data:
                    print(f"     • {item['metric_name']}: {item['value']} {item.get('units', '')}")
                    print(f"       Period: {item['period']}")
            else:
                print("     Warning: Response structure invalid")
                print(f"     Raw: {response.content[:200]}...")
        except Exception as e:
            print(f"     Could not parse JSON: {e}")
            print(f"     Raw response: {response.content[:200]}...")

        print()

    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False

    # Show cost summary
    print("4. Cost summary:")
    print("   " + "-" * 76)
    summary = client.get_cost_summary()
    print(f"   Total requests: {summary['total_requests']}")
    print(f"   Total tokens: {summary['total_tokens']:,}")
    print(f"   Total cost: ${summary['total_cost_usd']:.6f}")
    print(f"   Avg cost/request: ${summary['avg_cost_per_request']:.6f}")
    print()

    print("=" * 80)
    print("✓ All tests passed!")
    print("=" * 80)
    print()
    print("Next steps:")
    print("1. Integrate LLM client with extraction pipeline")
    print("2. Test with real SEC filings")
    print("3. Compare LLM vs rule-based extraction accuracy")
    print()

    return True


if __name__ == "__main__":
    success = test_basic_completion()
    sys.exit(0 if success else 1)
