-- Los roles anónimos/autenticados de Supabase recibieron EXECUTE explícito
-- sobre la función de auto-RLS; se revoca de forma segura si la función y roles existen.
do $$ begin
    revoke execute on function public.rls_auto_enable() from anon, authenticated;
exception when others then null;
end $$;
