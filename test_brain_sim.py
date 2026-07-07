import sys
import json
from dotenv import load_dotenv
load_dotenv()
from scrape_brain import session, BASE_URL
ar = session.get(f"{BASE_URL}/alphas/mLqjX8mx/recordset")
print(ar.status_code)
print(json.dumps(ar.json(), indent=2)[:1000])
