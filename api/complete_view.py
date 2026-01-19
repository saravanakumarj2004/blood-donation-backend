
class CompleteRequestView(APIView):
    def post(self, request):
        db = get_db()
        req_id = request.data.get('requestId')
        
        if not req_id:
             return Response({"error": "Request ID required"}, status=400)
             
        # Update Request Status
        res = db.requests.update_one(
            {"_id": ObjectId(req_id)},
            {"$set": {"status": "Completed"}}
        )
        
        if res.modified_count == 0:
             return Response({"error": "Request not found or already completed"}, status=404)
        
        # Determine who should be notified? Implementation details...
        # For now just success
        return Response({"success": True})
