import threading
import httpx
from supabase import create_client, Client
from config import Config
from werkzeug.local import LocalProxy

# Force HTTP/1.1 in httpx globally to fix HTTP/2 RemoteProtocolError and connection drop issues.
# Supabase-py enables http2=True by default which is unstable with long-lived idle connections in Waitress.
_original_init = httpx.Client.__init__

def _patched_init(self, *args, **kwargs):
    kwargs["http2"] = False
    _original_init(self, *args, **kwargs)

httpx.Client.__init__ = _patched_init

# Use threading.local() to ensure each Waitress thread gets its own Supabase client.
# This prevents httpx/h2 connection state corruption, as HTTP/2 connection pooling
# in httpx is not thread-safe and causes errors like "deque mutated during iteration".
_thread_local = threading.local()

def _get_client() -> Client:
    if not hasattr(_thread_local, "client"):
        _thread_local.client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    return _thread_local.client


def _get_admin_client() -> Client:
    if not hasattr(_thread_local, "admin_client"):
        _thread_local.admin_client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
    return _thread_local.admin_client


def get_supabase_client() -> Client:
    """
    Get a Supabase client using the anon/public key.
    Returns a LocalProxy so if imported globally, it dynamically resolves
    to the current thread's client instance when accessed.
    """
    return LocalProxy(_get_client)


def get_supabase_admin_client() -> Client:
    """
    Get a Supabase admin client using the service role key (bypasses RLS).
    Returns a LocalProxy for thread-safety.
    """
    return LocalProxy(_get_admin_client)
