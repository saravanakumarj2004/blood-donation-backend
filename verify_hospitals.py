
import os
import django
# from tabulate import tabulate

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from api.db import get_db

def list_hospitals():
    db = get_db()
    users = list(db.users.find({"role": "hospital"}, {"email": 1, "name": 1, "password": 1, "_id": 0}))
    
    print(f"\nFound {len(users)} Hospital Users in 'users' collection:\n")
    if users:
        print(f"{'Name':<35} | {'Email':<30} | {'Password'}")
        print("-" * 80)
        for u in users:
            print(f"{u.get('name', 'N/A'):<35} | {u.get('email', 'N/A'):<30} | {u.get('password', 'N/A')}")
    else:
        print("No hospital users found!")

if __name__ == "__main__":
    list_hospitals()
