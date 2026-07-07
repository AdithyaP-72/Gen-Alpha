import sys
import json
from dotenv import load_dotenv
load_dotenv()
from scrape_brain import session, BASE_URL
r = session.get(f"{BASE_URL}/alphas")
if r.status_code == 200:
    alphas = r.json().get("results", [])
    print(f"Auth successful, found {len(alphas)} alphas")
else:
    print(r.status_code, r.text)
