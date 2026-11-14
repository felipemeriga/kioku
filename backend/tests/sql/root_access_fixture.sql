-- Minimal disposable fixture, independent of production auth data.
do $$ begin
 if not exists(select 1 from pg_roles where rolname='anon') then create role anon; end if;
 if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated; end if;
 if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role; end if;
end $$;
create schema auth;
create table auth.users(id uuid primary key);
create table public.folders(id uuid primary key,user_id uuid references auth.users(id),parent_id uuid references public.folders(id));
