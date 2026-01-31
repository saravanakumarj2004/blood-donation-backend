"""
Authentication Utilities for JWT Token Validation
Ensures that:
1. JWT token is valid
2. User still exists in database
3. User has correct permissions
"""
import jwt
from django.conf import settings
from rest_framework.response import Response
from rest_framework import status
from functools import wraps
from .db import get_db
from bson import ObjectId

def authenticate_request(view_func):
    """
    Decorator to validate JWT token and verify user exists in database.
    Extracts user info and injects it into request.
    
    Usage:
        @authenticate_request
        def get(self, request):
            user_id = request.user_id  # Validated user ID
            user_role = request.user_role  # User role (donor/hospital/admin)
    """
    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        try:
            # 1. Extract Token from Authorization Header
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                return Response(
                    {"error": "Authorization token required", "code": "AUTH_REQUIRED"}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            token = auth_header.split(' ')[1]
            
            # 2. Decode and Validate JWT
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            except jwt.ExpiredSignatureError:
                return Response(
                    {"error": "Token has expired", "code": "TOKEN_EXPIRED"}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )
            except jwt.InvalidTokenError:
                return Response(
                    {"error": "Invalid token", "code": "INVALID_TOKEN"}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            user_id = payload.get('id')
            user_role = payload.get('role')
            
            if not user_id:
                return Response(
                    {"error": "Invalid token payload", "code": "INVALID_PAYLOAD"}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # 3. Verify User Still Exists in Database
            db = get_db()
            if db is None:
                return Response(
                    {"error": "Database Service Unavailable"}, 
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            try:
                user = db.users.find_one({"_id": ObjectId(user_id)})
            except Exception:
                # Invalid ObjectId format
                return Response(
                    {"error": "Invalid user identifier", "code": "INVALID_USER_ID"}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            if not user:
                return Response(
                    {"error": "User no longer exists", "code": "USER_NOT_FOUND"}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # 4. Inject validated user info into request
            request.user_id = user_id
            request.user_role = user_role
            request.user_data = user  # Full user object if needed
            
            # 5. Call the original view function
            return view_func(self, request, *args, **kwargs)
            
        except Exception as e:
            print(f"Authentication Error: {e}")
            return Response(
                {"error": "Authentication failed", "code": "AUTH_FAILED"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    return wrapper


def require_role(*allowed_roles):
    """
    Decorator to restrict access to specific user roles.
    Must be used AFTER @authenticate_request.
    
    Usage:
        @authenticate_request
        @require_role('donor')
        def get(self, request):
            # Only donors can access
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            user_role = getattr(request, 'user_role', None)
            
            if not user_role:
                return Response(
                    {"error": "Authentication required"}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            if user_role not in allowed_roles:
                return Response(
                    {"error": "Insufficient permissions", "code": "FORBIDDEN"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator
