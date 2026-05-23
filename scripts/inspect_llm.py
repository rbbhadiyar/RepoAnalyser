from dotenv import load_dotenv
import os
import inspect
from crewai import LLM

load_dotenv(override=True)
llm = LLM(model=os.environ.get('GROQ_MODEL','groq/llama-3.3-70b-versatile'), api_key=os.environ.get('GROQ_API_KEY'))
print('LLM repr', repr(llm))
print('LLM type', type(llm))
print('LLM dir', [name for name in dir(llm) if not name.startswith('_')])
if hasattr(llm, '__dict__'):
    print('LLM __dict__ keys', list(llm.__dict__.keys()))
print('LLM module', llm.__class__.__module__)
print('LLM init sig', inspect.signature(LLM))
