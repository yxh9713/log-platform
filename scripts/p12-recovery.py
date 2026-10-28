"""Outage checks ONLY against the dedicated synthetic logistics-p12 project."""
import csv
import hashlib
import http.cookiejar
import http.client
import io
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

COMPOSE=['docker','compose','-p','logistics-p12','-f','compose.verification.yaml','--profile','workers']
base='http://127.0.0.1:'+str(int(os.environ.get('P12_API_PORT','8012')))
portal='http://127.0.0.1:'+str(int(os.environ.get('P12_FRONTEND_PORT','5174')))


def control(*args:str)->None:
    subprocess.run([*COMPOSE,*args],check=True,stdout=subprocess.DEVNULL)


def code(path:str)->int:
    try:
        with urlopen(base+path,timeout=5) as response:return response.status
    except HTTPError as error:return error.code
    except (URLError, OSError, http.client.HTTPException):return 0


def wait_ready()->None:
    until=time.monotonic()+40
    while time.monotonic()<until:
        if code('/health/ready')==200:return
        time.sleep(.5)
    raise RuntimeError('Isolated API readiness did not recover')


def main()->None:
    # Guard by actual server identity before any stop/restart operation.
    guard="from app.config import DatabaseSettings; from app.db.connection import create_database_engine; import sqlalchemy as s; c=DatabaseSettings(); e=create_database_engine(c); t=e.connect(); current=t.execute(s.text('SELECT current_database()')).scalar_one(); t.close(); e.dispose();\nif c.app_env!='test' or current!='logistics_p12':raise RuntimeError('Not isolated P12')"
    subprocess.run([*COMPOSE,'exec','-T','api','python','-c',guard],check=True)
    client=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def get(path:str):
        with client.open(portal+path,timeout=10) as response:return json.load(response)
    def mutation(path:str,method:str='POST'):
        with client.open(Request(portal+path,data=b'{}' if method=='POST' else None,method=method,headers={'Content-Type':'application/json','X-Requested-With':'logistics-web'}),timeout=10) as response:return response.status,json.load(response)
    def accept()->str:
        before={item['id'] for item in get('/v1/exports')['items']}
        status,ack=mutation('/v1/shipments?export=1','GET')
        assert status==202 and ack=={'message':'we start to process data'}
        ids=[item['id'] for item in get('/v1/exports')['items'] if item['id'] not in before]
        assert len(ids)==1
        return ids[0]
    report={}
    try:
        with client.open(Request(portal+'/v1/login',data=json.dumps({'email':'admin@paychex.example','password':'synthetic-p12-browser-only','slug':'paychex'}).encode(),headers={'Content-Type':'application/json'}),timeout=10):pass
        control('stop','-t','5','redis')
        assert code('/health/live')==200 and code('/health/ready')==503
        assert get('/v1/shipments')['total']==2
        redis_job=accept()
        try:
            client.open(Request(portal+'/v1/login',data=b'{"email":"admin@paychex.example","password":"synthetic-p12-browser-only","slug":"paychex"}',headers={'Content-Type':'application/json'}),timeout=10)
            raise AssertionError('Login unexpectedly bypassed unavailable limiter')
        except HTTPError as error:assert error.code==503
        control('start','redis');wait_ready()
        report['redis_outage']='live 200, ready 503; existing session/query/export work; login fails closed; recovered'
        control('stop','-t','5','export-worker')
        job=accept();assert get('/v1/exports/'+job)['state']=='pending'
        started=time.monotonic();control('restart','-t','8','api');wait_ready()
        report['api_restart_seconds']=round(time.monotonic()-started,3)
        assert get('/v1/exports/'+job)['state']=='pending'
        control('start','export-worker')
        until=time.monotonic()+30
        while time.monotonic()<until and get('/v1/exports/'+job)['state']!='ready':time.sleep(.5)
        ready=get('/v1/exports/'+job);assert ready['state']=='ready'
        with client.open(portal+ready['url'],timeout=10) as response:data=response.read()
        rows=list(csv.reader(io.StringIO(data.decode())))
        assert len(rows)==3 and len(rows[0])==7
        original=hashlib.sha256(data).hexdigest()
        control('stop','-t','5','postgres')
        assert code('/health/live')==200 and code('/health/ready')==503
        try:get('/v1/session');raise AssertionError('Session unexpectedly bypassed database')
        except HTTPError as error:assert error.code==503 and 'password' not in error.read().decode().lower()
        control('start','postgres');wait_ready()
        with client.open(portal+ready['url'],timeout=10) as response:assert hashlib.sha256(response.read()).hexdigest()==original
        report['postgres_outage']='live 200, ready/auth 503; same session and identical ready artifact recovered'
        report['worker_outage']='queued before restart, generated after resume; real 2-row CSV'
        for identity in (job,redis_job):
            until=time.monotonic()+30
            while time.monotonic()<until and get('/v1/exports/'+identity)['state']!='ready':time.sleep(.5)
            assert get('/v1/exports/'+identity)['state']=='ready'
            mutation('/v1/exports/'+identity+'/dismiss')
        mutation('/v1/logout')
        Path('.local/p12/recovery.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
    finally:
        # Restore isolated services even if an assertion fails; never touch the main project.
        control('start','postgres','redis','api','frontend','export-worker','pod-worker')
        wait_ready()


if __name__=='__main__':main()
