"""Verify real CSV worker/SSE/download recovery without displaying credentials or rows."""
import argparse
import csv
import http.cookiejar
import io
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

COLUMNS = ['shipment_number', 'carrier', 'route', 'order_date', 'due_date', 'pod_name', 'deliver_time']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials-file', type=Path, required=True)
    args = parser.parse_args()
    base = 'http://127.0.0.1:' + str(int(os.environ.get('FRONTEND_PORT', '5173')))
    try:
        credentials = json.loads(args.credentials_file.read_text())['users']
        clients = []
        identities = []
        for credential in credentials:
            client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with client.open(Request(base+'/v1/login', data=json.dumps({'email':credential['email'], 'password':credential['password'], 'slug':credential['company_slug']}).encode(), headers={'Content-Type':'application/json'}), timeout=10) as response:
                assert response.status == 200
            with client.open(base+'/v1/exports', timeout=10) as response:
                before = {item['id'] for item in json.load(response)['items']}
            with client.open(Request(base+'/v1/shipments?export=1', headers={'X-Requested-With':'logistics-web'}), timeout=10) as response:
                assert response.status == 202 and json.load(response) == {'message':'we start to process data'}
            with client.open(base+'/v1/exports', timeout=10) as response:
                added = [item['id'] for item in json.load(response)['items'] if item['id'] not in before]
            assert len(added) == 1
            identities.append(added[0]); clients.append(client)
        assert len(clients) == 2
        for index, client in enumerate(clients):
            ready = None
            # Each new stream replays durable state. Read actual proxy SSE frames.
            with client.open(base+'/v1/exports/events', timeout=20) as response:
                assert response.headers['Content-Type'].startswith('text/event-stream')
                deadline = time.monotonic()+30
                while time.monotonic() < deadline:
                    line = response.readline().decode().strip()
                    if line.startswith('data: '):
                        items = json.loads(line[6:]).get('items', [])
                        assert all(item['id'] != identities[1-index] for item in items)
                        found = [item for item in items if item['id'] == identities[index]]
                        if found and found[0]['state'] == 'ready':
                            ready = found[0]; break
                        assert not found or found[0]['state'] != 'failed'
            assert ready is not None
            with client.open(base+ready['url'], timeout=10) as response:
                assert response.headers['Content-Disposition'].startswith('attachment; filename="shipment-')
                rows = list(csv.reader(io.StringIO(response.read().decode())))
                assert rows[0] == COLUMNS and len(rows)-1 == ready['row_count']
                assert all(len(row) == 7 for row in rows)
            try:
                clients[1-index].open(base+ready['url'], timeout=10)
                raise AssertionError('Another requester downloaded an export')
            except HTTPError as failure:
                assert failure.code == 404
            # Reconnect/reload recovery retains the exact artifact before dismissal.
            with client.open(base+'/v1/exports/'+identities[index], timeout=10) as response:
                assert json.load(response)['url'] == ready['url']
            with client.open(Request(base+'/v1/exports/'+identities[index]+'/dismiss', data=b'{}', headers={'Content-Type':'application/json','X-Requested-With':'logistics-web'}), timeout=10) as response:
                assert response.status == 200
        for client in clients:
            with client.open(Request(base+'/v1/logout', data=b'{}', headers={'Content-Type':'application/json','X-Requested-With':'logistics-web'}), timeout=10) as response:
                assert response.status == 200
        print('Export smoke passed: both roles, durable jobs, real worker CSV, proxy SSE, recovery, requester-isolated download and dismissal; no rows or credentials displayed')
        return 0
    except Exception:
        print('Export smoke failed; inspect local worker and job status. No credentials or CSV rows displayed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
