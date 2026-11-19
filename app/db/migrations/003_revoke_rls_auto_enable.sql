-- Los roles anónimos/autenticados de Supabase recibieron EXECUTE explícito
-- sobre la función de auto-RLS; se revoca para cerrar el endpoint RPC.
revoke execute on function public.rls_auto_enable() from anon, authenticated;
