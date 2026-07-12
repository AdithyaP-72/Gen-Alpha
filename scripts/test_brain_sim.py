import sys
import json
from dotenv import load_dotenv
load_dotenv()
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from genalpha.scrape_brain import get_session, BASE_URL
session = get_session()
ar = session.get(f"{BASE_URL}/alphas/mLqjX8mx/recordset")
print(ar.status_code)
print(json.dumps(ar.json(), indent=2)[:1000])
