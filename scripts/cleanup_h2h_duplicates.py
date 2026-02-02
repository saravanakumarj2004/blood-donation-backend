
import os
import sys
import datetime
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
MONGO_URI = os.getenv('MONGO_URI', "mongodb://localhost:27017/")
DB_NAME = os.getenv('MONGO_DB_NAME', "blood_donation_db")

print(f"Connecting to MongoDB: {MONGO_URI} (DB: {DB_NAME})")

try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    print("Connected successfully.")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    sys.exit(1)

def revert_stock_usage(hospital_id, bg, units, source_batch_ids):
    """
    Reverts the stock usage:
    1. Adds units back to Inventory (Aggregate).
    2. Adds units back to Batches (Physical).
    """
    print(f"  -> Reverting {units} units of {bg} for Hospital {hospital_id}...")
    
    # 1. Revert Inventory
    res_inv = db.inventory.update_one(
        {"hospitalId": hospital_id},
        {"$inc": {bg: units}}
    )
    print(f"     Inventory updated: {res_inv.modified_count} doc(s)")

    # 2. Revert Batches
    for batch_info in source_batch_ids:
        batch_id_str = batch_info.get('batchId')
        used_qty = batch_info.get('unitsUsed', 0)
        
        if batch_id_str and used_qty > 0:
            try:
                # Add units back
                # Also reset status if it was Depleted
                db.batches.update_one(
                    {"_id": ObjectId(batch_id_str)},
                    {
                        "$inc": {"units": used_qty},
                        "$set": {"status": "Active"} # Force Active (check expiry logically if needed, but safe for now)
                    }
                )
                # Remove depletedAt if present
                db.batches.update_one(
                     {"_id": ObjectId(batch_id_str)},
                     {"$unset": {"depletedAt": ""}}
                )
                print(f"     Refilled Batch {batch_id_str} by {used_qty} units.")
            except Exception as e:
                print(f"     Failed to update batch {batch_id_str}: {e}")

def main():
    print("Starting cleanup of duplicate Outgoing Batches...")
    
    # Find all outgoing batches of type 'transfer'
    cursor = db.outgoing_batches.find({"type": "transfer"})
    
    # Group by dispatchDetails.requestId
    groups = {}
    for doc in cursor:
        req_id = doc.get('dispatchDetails', {}).get('requestId')
        if not req_id:
            continue
        
        if req_id not in groups:
            groups[req_id] = []
        groups[req_id].append(doc)

    duplicates_found = 0
    start_time = datetime.datetime.now()

    for req_id, docs in groups.items():
        if len(docs) > 1:
            duplicates_found += 1
            print(f"\n[Request ID: {req_id}] Found {len(docs)} records.")
            
            # Sort by createdAt ascending (Keep the first one)
            # Handle string dates
            docs.sort(key=lambda x: x.get('createdAt', ''))
            
            original = docs[0]
            duplicates = docs[1:]
            
            print(f"  Keeping Original: {original['_id']} (Created: {original.get('createdAt')})")
            
            for dup in duplicates:
                print(f"  PROCESSING DUPLICATE: {dup['_id']} (Created: {dup.get('createdAt')})")
                
                hospital_id = dup.get('hospitalId')
                bg = dup.get('bloodGroup')
                units = dup.get('quantity', 0)
                source_batches = dup.get('sourceBatchIds', [])
                
                # Revert Stock
                revert_stock_usage(hospital_id, bg, units, source_batches)
                
                # Delete Duplicate
                db.outgoing_batches.delete_one({"_id": dup['_id']})
                print(f"  -> Deleted duplicate record {dup['_id']}")

    print("\n" + "="*30)
    print(f"Cleanup Complete.")
    print(f"Processed {len(groups)} request groups.")
    print(f"Found and cleaned {duplicates_found} duplicate groups.")
    print("="*30)

if __name__ == "__main__":
    main()
