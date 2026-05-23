import inspect
import crewai
from crewai import LLM

print('crewai module', crewai.__file__)
print('LLM signature', inspect.signature(LLM))
print('LLM doc', LLM.__doc__[:400] if LLM.__doc__ else 'no doc')
