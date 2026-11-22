from supabase import Client, create_client

from .config import SUPABASE_SERVICE_KEY, SUPABASE_URL

sb: Client | None = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_KEY else None
