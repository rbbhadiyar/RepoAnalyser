import requests, time

resp = requests.post('http://127.0.0.1:5000/analyze', json={'repo_url':'https://github.com/rbbhadiyar/RepoAnalyser'})
print('analyze resp:', resp.status_code, resp.text)
if resp.status_code != 200:
    raise SystemExit()
job_id = resp.json().get('job_id')
print('job_id:', job_id)

for i in range(60):
    time.sleep(2)
    r = requests.get(f'http://127.0.0.1:5000/export/json/{job_id}')
    if r.status_code == 200:
        print('Report ready')
        data = r.json()
        print('file_count:', data.get('meta',{}).get('file_count'))
        print('preview:', data.get('raw','')[:500])
        break
    else:
        print(i, 'waiting...')
else:
    print('timed out waiting for report')
