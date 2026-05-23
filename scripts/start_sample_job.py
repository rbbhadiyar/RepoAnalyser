from app import run_analysis, progress_queues
import uuid, threading, time

job_id = str(uuid.uuid4())
progress_queues[job_id] = __import__('queue').Queue()
repo_url = 'https://github.com/rbbhadiyar/RepoAnalyser'

def worker():
    run_analysis(job_id, repo_url)

threading.Thread(target=worker, daemon=True).start()

q = progress_queues[job_id]
while True:
    item = q.get()
    if item is None:
        break
    print(item)
