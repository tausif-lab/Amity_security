import requests
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission


class SupabaseUser:
    is_authenticated = True

    def __init__(self, id, email, role):
        self.id, self.email, self.role = id, email, role


class SupabaseAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header[7:]
        h = {"apikey": settings.SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"}

        r = requests.get(f"{settings.SUPABASE_URL}/auth/v1/user", headers=h, timeout=10)
        if r.status_code != 200:
            raise AuthenticationFailed("Invalid or expired token")
        u = r.json()

        p = requests.get(
            f"{settings.SUPABASE_URL}/rest/v1/profiles",
            params={"select": "role", "id": f"eq.{u['id']}"},
            headers=h, timeout=10,
        )
        rows = p.json() if p.status_code == 200 else []
        role = rows[0]["role"] if rows else None
        return (SupabaseUser(u["id"], u["email"], role), token)


def role_required(*roles):
    class _RolePermission(BasePermission):
        def has_permission(self, request, view):
            return getattr(request.user, "role", None) in roles
    return _RolePermission