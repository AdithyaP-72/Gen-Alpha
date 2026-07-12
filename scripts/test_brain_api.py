import sys
import json
from dotenv import load_dotenv
load_dotenv()
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from genalpha.scrape_brain import get_session, BASE_URL
session = get_session()
r = session.get(f"{BASE_URL}/alphas")
if r.status_code == 200:
    alphas = r.json().get("results", [])
    print(f"Auth successful, found {len(alphas)} alphas")
else:
    print(r.status_code, r.text)
