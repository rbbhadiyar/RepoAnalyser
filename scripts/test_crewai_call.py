from dotenv import load_dotenv
import os
from crewai import LLM

load_dotenv(override=True)
llm = LLM(model=os.environ.get('GROQ_MODEL', 'groq/llama-3.3-70b-versatile'), api_key=os.environ.get('GROQ_API_KEY'))
print('LLM repr', llm)
try:
    result = llm.call('Hello')
    print('Result type', type(result))
    print('Result', result)
except Exception as e:
    print('Error', repr(e))
