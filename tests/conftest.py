"""Disable Groq during unit/integration tests — engine + safety gate still run."""
import os

os.environ["RG_AI_DISABLE"] = "1"
os.environ["GROQ_API_KEY"] = ""
