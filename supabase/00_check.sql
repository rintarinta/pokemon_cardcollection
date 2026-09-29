-- 00_check.sql : 現状確認用（読み取りのみ。何も変更しません）
-- Supabase ダッシュボード > SQL Editor に貼って Run。結果は 01 の実行前後で見比べます。

-- 1) 対象テーブルの RLS 有効/無効
select c.relname as table_name, c.relrowsecurity as rls_enabled
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('collections','set_images','card_images','card_rarities','card_names','custom_cards','app_admins')
order by 1;

-- 2) 今あるポリシー（誰が何をできるか）
select tablename, policyname, cmd, roles, qual as using_expr, with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;

-- 3) 件数（01 実行後も同じ数になっていればデータは無傷）
select 'collections'   as t, count(*) from public.collections   union all
select 'set_images',          count(*) from public.set_images    union all
select 'card_images',         count(*) from public.card_images   union all
select 'card_rarities',       count(*) from public.card_rarities union all
select 'card_names',          count(*) from public.card_names    union all
select 'custom_cards',        count(*) from public.custom_cards;

-- 4) 登録ユーザー（知らないアカウントが無いか確認）
select id, email, created_at, last_sign_in_at from auth.users order by created_at;
