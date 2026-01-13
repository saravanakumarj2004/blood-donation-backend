import os
import django
from django.conf import settings

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from api.db import get_db

def inspect_database():
    db = get_db()
    print(f"\n--- Inspecting Database: {settings.MONGO_DB_NAME} ---")
    
    collection_names = db.list_collection_names()
    print(f"Collections found: {collection_names}\n")
    
    for col_name in collection_names:
        count = db[col_name].count_documents({})
        print(f"Collection: '{col_name}' ({count} documents)")
        if count > 0:
            # Print first 3 docs
            cursor = db[col_name].find().limit(3)
            for doc in cursor:
                # Remove ID for cleaner print if needed, or keeping it is fine
                doc['_id'] = str(doc['_id']) 
                print(f"  - {doc}")
        print("-" * 30)

if __name__ == "__main__":
    inspect_database()
