-- 01_protect_shared_master.sql
-- 共有マスタ（set_images / card_images / card_rarities / card_names / custom_cards）を
--   読む   : 誰でも（未ログイン含む）
--   書く・消す : 管理者だけ
-- にし、collections（各自の所有データ）は本人の行だけ読み書きできるようにする。
-- データ自体は消しません。何度実行しても同じ結果になります。
--
-- ★実行前に下の YOUR_LOGIN_ID@example.com をご自身のログインIDに書き換えてください。

begin;

-- ===== 管理者テーブル =====
create table if not exists public.app_admins (
  user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.app_admins enable row level security;
-- ポリシーを作らない = API からは誰も読めない・書けない（SQL Editor からのみ管理）
revoke all on public.app_admins from anon, authenticated;

insert into public.app_admins (user_id)
select id from auth.users where email = lower('YOUR_LOGIN_ID@example.com')
on conflict do nothing;

-- ログイン中のユーザーが管理者か（アプリの表示切替と RLS の両方で使う）
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.app_admins where user_id = auth.uid());
$$;
revoke all on function public.is_admin() from public;
grant execute on function public.is_admin() to anon, authenticated;

-- ===== 既存ポリシーを全部はずしてから作り直す =====
do $$
declare p record;
begin
  for p in
    select tablename, policyname from pg_policies
    where schemaname = 'public'
      and tablename in ('collections','set_images','card_images','card_rarities','card_names','custom_cards')
  loop
    execute format('drop policy %I on public.%I', p.policyname, p.tablename);
  end loop;
end $$;

-- ===== 共有マスタ：読むのは誰でも、書くのは管理者だけ =====
do $$
declare t text;
begin
  foreach t in array array['set_images','card_images','card_rarities','card_names','custom_cards'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon', t);
    execute format('grant select on public.%I to anon, authenticated', t);
    execute format('grant insert, update, delete on public.%I to authenticated', t);
    execute format('create policy "read_all" on public.%I for select to anon, authenticated using (true)', t);
    execute format('create policy "admin_insert" on public.%I for insert to authenticated with check ((select public.is_admin()))', t);
    execute format('create policy "admin_update" on public.%I for update to authenticated using ((select public.is_admin())) with check ((select public.is_admin()))', t);
    execute format('create policy "admin_delete" on public.%I for delete to authenticated using ((select public.is_admin()))', t);
  end loop;
end $$;

-- ===== collections：本人の行だけ =====
alter table public.collections enable row level security;
alter table public.collections alter column user_id set default auth.uid();
revoke all on public.collections from anon;
grant select, insert, update, delete on public.collections to authenticated;
create policy "own_select" on public.collections for select to authenticated using (user_id = (select auth.uid()));
create policy "own_insert" on public.collections for insert to authenticated with check (user_id = (select auth.uid()));
create policy "own_update" on public.collections for update to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy "own_delete" on public.collections for delete to authenticated using (user_id = (select auth.uid()));

-- ===== 画像URLは http(s) か data:image のみ（XSS 対策の二重化）=====
-- NOT VALID = 既存の行はチェックしない（既存データで失敗しないように）。新規・更新分から効く。
alter table public.card_images  drop constraint if exists card_images_url_scheme;
alter table public.card_images  add  constraint card_images_url_scheme
  check (url ~* '^(https?://|data:image/(png|jpe?g|webp|gif);base64,)') not valid;
alter table public.set_images   drop constraint if exists set_images_url_scheme;
alter table public.set_images   add  constraint set_images_url_scheme
  check (url_template ~* '^https?://') not valid;
alter table public.custom_cards drop constraint if exists custom_cards_url_scheme;
alter table public.custom_cards add  constraint custom_cards_url_scheme
  check (image_url is null or image_url ~* '^(https?://|data:image/(png|jpe?g|webp|gif);base64,)') not valid;

commit;

-- ===== 確認（00_check.sql の件数と同じ・admin_count = 1 ならOK）=====
select (select count(*) from public.app_admins) as admin_count;
select 'collections'   as t, count(*) from public.collections   union all
select 'set_images',          count(*) from public.set_images    union all
select 'card_images',         count(*) from public.card_images   union all
select 'card_rarities',       count(*) from public.card_rarities union all
select 'card_names',          count(*) from public.card_names    union all
select 'custom_cards',        count(*) from public.custom_cards;
select tablename, policyname, cmd, roles from pg_policies where schemaname = 'public' order by 1, 2;
