import os
from dotenv import load_dotenv

# Load .env so local keys are available during the check
load_dotenv(override=True)

print("FORCE_LOCAL_FALLBACK=", os.environ.get("FORCE_LOCAL_FALLBACK"))
print("GROQ_API_KEY env present=", bool(os.environ.get("GROQ_API_KEY")))
print("OPENAI_API_KEY env present=", bool(os.environ.get("OPENAI_API_KEY")))
