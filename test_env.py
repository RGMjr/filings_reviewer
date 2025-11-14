"""
Quick test to verify your .env file is configured correctly
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Check if API key exists
api_key = os.getenv("OPENAI_API_KEY")

print("=" * 50)
print("Environment Configuration Test")
print("=" * 50)

if not api_key:
    print("❌ ERROR: OPENAI_API_KEY not found in .env file")
    print("\nMake sure:")
    print("1. You have a .env file in the project root")
    print("2. It contains: OPENAI_API_KEY=your_key_here")
    print("3. There are no extra spaces around the = sign")
elif api_key == "your_openai_api_key_here":
    print("⚠️  WARNING: Using placeholder API key")
    print("\nPlease update your .env file with your actual OpenAI API key")
    print("Get one from: https://platform.openai.com/api-keys")
elif not api_key.startswith("sk-"):
    print("⚠️  WARNING: API key format looks incorrect")
    print(f"   Key starts with: {api_key[:10]}...")
    print("\nOpenAI API keys should start with 'sk-'")
else:
    print("✓ .env file loaded successfully")
    print(f"✓ API key found (starts with: {api_key[:15]}...)")
    print(f"✓ Key length: {len(api_key)} characters")
    print("\n✓ Configuration looks good!")
    print("\nYou can now run: python data_preprocessing.py")

print("=" * 50)
