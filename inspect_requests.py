
import os
import sys
import django
from bson import ObjectId

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from api.db import get_db

db = get_db()
print("--- ALL REQUESTS ---")
for req in db.requests.find():
    print(req)
