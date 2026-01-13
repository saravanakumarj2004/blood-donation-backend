
class AdminAnalyticsView(APIView):
    def get(self, request):
        db = get_db()
        
        # 1. Donation Trends (Last 6 Months)
        # Assuming 'appointments' has 'date' field (ISO string) and status 'Completed'
        trends_pipeline = [
            {
                "$match": {
                    "status": "Completed",
                    "date": {"$exists": True}
                }
            },
            {
                "$group": {
                    "_id": {
                        "year": {"$year": {"$dateFromString": {"dateString": "$date"}}},
                        "month": {"$month": {"$dateFromString": {"dateString": "$date"}}}
                    },
                    "count": {"$sum": 1}
                }
            },
            { "$sort": { "_id.year": 1, "_id.month": 1 } }
        ]
        
        # Note: $dateFromString requires 'date' to be in ISO format.
        # If dates are stored loosely, this might fail. We should check data format.
        # Fallback: Python processing if aggregation is risky.
        
        # Python Processing Approach (Safer given unknown date format consistency)
        donations = list(db.appointments.find({"status": "Completed"}))
        monthly_counts = {}
        for d in donations:
            try:
                dt = datetime.datetime.fromisoformat(d.get('date').replace('Z', '+00:00'))
                key = dt.strftime('%b %Y') # e.g., "Jan 2024"
                monthly_counts[key] = monthly_counts.get(key, 0) + 1
            except:
                pass
                
        # Fill last 6 months 
        today = datetime.datetime.now()
        trend_data = []
        for i in range(5, -1, -1):
            date = today - datetime.timedelta(days=i*30)
            key = date.strftime('%b %Y')
            trend_data.append({
                "month": key,
                "count": monthly_counts.get(key, 0)
            })

        # 2. Recent Activities (Fake "Reports" based on real events)
        # We'll fetch the last 5 Emergency Alerts or Registrations to show as "System Events"
        recent_alerts = list(db.requests.find().sort("timestamp", -1).limit(5))
        activities = []
        for alert in recent_alerts:
            activities.append({
                "id": str(alert['_id']),
                "type": "Emergency Alert",
                "desc": f"Alert for {alert.get('units')} units {alert.get('bloodGroup')}",
                "date": alert.get('timestamp')
            })

        return Response({
            "trends": trend_data,
            "activities": activities
        })
