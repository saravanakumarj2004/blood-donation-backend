import os
import django
from django.conf import settings

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from api.db import get_db

def clean_database():
    db = get_db()
    
    print("--- Cleaning Database (ALL Collections) ---")
    
    collection_names = db.list_collection_names()
    
    for col_name in collection_names:
        # Skip system collections if any (though typically hidden)
        if col_name.startswith("system."):
            continue
            
        result = db[col_name].delete_many({})
        # Or db[col_name].drop() to completely remove
        # db[col_name].drop() 
        print(f"Cleared collection '{col_name}': {result.deleted_count} documents removed")
        
    print("--- Database Completely Cleaned ---")

if __name__ == "__main__":
    clean_database()
