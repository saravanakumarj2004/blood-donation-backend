from pymongo import MongoClient
from django.conf import settings
import sys

try:
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]
    # Simple check
    # client.server_info() 
    print(f"Connected to MongoDB at {settings.MONGO_URI}, DB: {settings.MONGO_DB_NAME}")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    # In production, we might want to fail hard, but for dev we'll carry on
    db = None

def get_db():
    return db
