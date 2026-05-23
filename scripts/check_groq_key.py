from dotenv import load_dotenv
import os

load_dotenv(override=True)
print('GROQ_API_KEY=', os.environ.get('GROQ_API_KEY'))
print('GROQ_MODEL=', os.environ.get('GROQ_MODEL', 'groq/llama-3.3-70b-versatile'))
try:
    import litellm
    print('litellm imported', getattr(litellm, '__version__', 'no version'))
    try:
        resp = litellm.completion(
            model=os.environ.get('GROQ_MODEL', 'groq/llama-3.3-70b-versatile'),
            api_key=os.environ.get('GROQ_API_KEY'),
            messages=[{'role': 'user', 'content': 'Hello'}],
            max_tokens=1,
        )
        print('OK', resp)
    except Exception as e:
        print('completion error:', repr(e))
except Exception as e:
    print('import error:', repr(e))
