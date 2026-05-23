import uuid
from app import run_analysis, progress_queues
import queue

job_id = 'manual-test'
progress_queues[job_id] = queue.Queue()
repo_url = 'https://github.com/rbbhadiyar/RepoAnalyser'

# Run synchronously in this process so output appears in terminal
run_analysis(job_id, repo_url)

# Stream progress
q = progress_queues[job_id]
while True:
    item = q.get()
    if item is None:
        break
    print(item)
