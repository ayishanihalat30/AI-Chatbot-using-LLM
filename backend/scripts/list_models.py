"""List Gemini models your API key can use for chat and embeddings.

Usage (same terminal where GEMINI_API_KEY is set):  python scripts/list_models.py
"""
import os
import sys

from google import genai

key = os.environ.get("GEMINI_API_KEY")
if not key:
    sys.exit("Set GEMINI_API_KEY first.")

client = genai.Client(api_key=key)
chat, embed = [], []
for m in client.models.list():
    actions = m.supported_actions or []
    name = (m.name or "").removeprefix("models/")
    if "generateContent" in actions:
        chat.append(name)
    if "embedContent" in actions:
        embed.append(name)

print("CHAT models (generateContent):")
for n in sorted(chat):
    print("  ", n)
print("\nEMBEDDING models (embedContent):")
for n in sorted(embed):
    print("  ", n)
