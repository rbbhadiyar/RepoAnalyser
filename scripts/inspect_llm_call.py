from dotenv import load_dotenv
import os
import inspect
from crewai import LLM

load_dotenv(override=True)
llm = LLM(model=os.environ.get('GROQ_MODEL', 'groq/llama-3.3-70b-versatile'), api_key=os.environ.get('GROQ_API_KEY'))
print('LLM.call sig', inspect.signature(llm.call))
print('LLM.acall sig', inspect.signature(llm.acall))
print('LLM.call doc:', llm.call.__doc__)
print('LLM.__class__', llm.__class__)
print('LLM attrs count', len([a for a in dir(llm) if not a.startswith('_')]))
