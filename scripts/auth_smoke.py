"""Exercise real seeded login over the Vite proxy without printing credentials."""

import argparse
import http.cookiejar
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--check-areas", action="store_true", help="Also verify the P4 protected area read")
    parser.add_argument("--check-queries", action="store_true", help="Also verify P5 Tracking and Search reads")
    parser.add_argument("--check-day", action="store_true", help="Also verify P10 My Day and area statistics")
    args = parser.parse_args()
    try:
        frontend_port = int(os.environ.get("FRONTEND_PORT", "5173"))
        api_port = int(os.environ.get("API_PORT", "8000"))
        assert 1 <= frontend_port <= 65535 and 1 <= api_port <= 65535
        base = "http://127.0.0.1:" + str(frontend_port)
        direct = "http://127.0.0.1:" + str(api_port)
        credentials = json.loads(args.credentials_file.read_text())["users"]
        assert len(credentials) == 2
        roles = set()
        for credential in credentials:
            client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
            payload = {"email": credential["email"], "password": credential["password"],
                       "slug": credential["company_slug"]}
            request = Request(base + "/v1/login", data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"})
            with client.open(request, timeout=10) as response:
                assert response.status == 200
                token = json.load(response)["token"]
            with client.open(base + "/v1/session", timeout=10) as response:
                session = json.load(response)
            assert session["email"] == credential["email"]
            assert session["company"]["slug"] == credential["company_slug"]
            roles.add(session["role"])
            if args.check_areas:
                with client.open(base + "/v1/areas", timeout=10) as response:
                    areas = json.load(response)
                assert isinstance(areas, list)
                assert all(isinstance(item["id"], int) and isinstance(item["name"], str) for item in areas)
            if args.check_queries:
                with client.open(base + "/v1/shipments", timeout=10) as response:
                    tracking = json.load(response)
                    assert response.headers["Cache-Control"] == "no-store"
                assert isinstance(tracking["items"], list)
                assert tracking["total"] == tracking["metrics"]["total"]
                assert tracking["page"] == 1 and tracking["length"] == 10
                with client.open(base + "/v1/shipments/search?identifier=smoke_" + uuid.uuid4().hex, timeout=10) as response:
                    search = json.load(response)
                assert search["total"] == 0 and search["items"] == []
                assert search["field"] == "reference"
            if args.check_day:
                with client.open(base + "/v1/my-day", timeout=10) as response:
                    day = json.load(response)
                    assert response.headers["Cache-Control"] == "no-store"
                stats = day["stats"]
                assert stats["total"] == stats["delivered"] + stats["undelivered"] + stats["void"]
                assert 0 <= stats["otp"] <= 100
                assert all(day["exceptions"][key] == 0 for key in ("consolidated", "no_package", "held"))
                assert sum(item["total"] for item in day["areas"]) <= stats["total"]
                assert [item["area"] for item in day["areas"]] == sorted(item["area"] for item in day["areas"])
                for path in ("shipment-stats", "exceptions-stats", "area-stats"):
                    with client.open(base + "/v1/" + path, timeout=10) as response:
                        assert isinstance(json.load(response)["report_date"], str)
            with client.open(base + "/v1/session", timeout=10) as response:
                assert json.load(response) == session  # cookie restore
            with client.open(Request(direct + "/v1/session", headers={"Authorization": "Bearer " + token}), timeout=10) as response:
                assert json.load(response) == session
            request = Request(base + "/v1/logout", data=b"{}", headers={
                "Content-Type": "application/json", "X-Requested-With": "logistics-web"})
            with client.open(request, timeout=10) as response:
                assert json.load(response) == {"message": "Signed out"}
            for headers in ({}, {"Authorization": "Bearer " + token}):
                try:
                    client.open(Request(base + "/v1/session", headers=headers), timeout=10)
                    raise AssertionError("Revoked token was accepted")
                except HTTPError as error:
                    assert error.code == 401
        assert roles == {"administrator", "user"}
    except Exception:
        print("Authentication smoke failed; check the local services and private file.", file=sys.stderr)
        return 1
    print("Authentication smoke passed: both seeded roles, proxy login, cookie restore, bearer access and logout revocation; no credentials displayed")
    if args.check_queries:
        print("P5 query smoke passed: both roles, Tracking metrics/pagination and exact reference Search")
    if args.check_day:
        print("My Day smoke passed: both roles, combined UTC snapshot and approved statistics routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
