-- Seed data: you (the owner) and the automated-test user.
-- Edit the THREE values in the first statement, then run:  make seed
-- (or paste the whole file into the Supabase SQL editor).
-- Safe to run again: nothing is inserted twice.

-- >>> EDIT THESE THREE VALUES (keep the $v$ ... $v$ quoting; no other changes needed) <<<
create temp table seed_input as
select
    $v$<Your name>$v$ as display_name,
    -- short context the AI uses when judging your email, e.g. Final-year B.Tech CSE student in Pune
    $v$<About you>$v$ as about,
    -- numeric Telegram id: message @userinfobot on Telegram to get it
    $v$<telegram_user_id>$v$ as telegram_id;

do $$
declare
    v_name  text;
    v_about text;
    v_tg    text;
    v_uid   uuid;
begin
    select display_name, about, telegram_id into v_name, v_about, v_tg from seed_input;

    -- Refuse to run with the placeholders still in place.
    if v_name like '<%' or v_about like '<%' then
        raise exception 'Edit the name and about values at the top of db/seed.sql first.';
    end if;
    if v_tg !~ '^[0-9]+$' then
        raise exception 'telegram_id must be your numeric Telegram id (digits only), got: %', v_tg;
    end if;

    -- 1) You
    if not exists (select 1 from channel_identities where channel = 'telegram' and channel_user_id = v_tg) then
        insert into users (display_name, about) values (v_name, v_about) returning id into v_uid;
        insert into user_settings (user_id) values (v_uid);
        insert into channel_identities (user_id, channel, channel_user_id, chat_id)
        values (v_uid, 'telegram', v_tg, v_tg);
    end if;

    -- 2) A separate user for the automated golden tests (its replies are never sent anywhere)
    if not exists (select 1 from channel_identities where channel = 'test' and channel_user_id = 'golden-tester') then
        insert into users (display_name, about) values ('Golden Tester', 'test account') returning id into v_uid;
        insert into user_settings (user_id, preferred_channel) values (v_uid, 'test');
        insert into channel_identities (user_id, channel, channel_user_id, chat_id)
        values (v_uid, 'test', 'golden-tester', 'golden-tester');
    end if;
end
$$;

-- Result: expect two rows, one 'telegram' (you) and one 'test' (Golden Tester).
select u.display_name, ci.channel, ci.channel_user_id, u.id as user_id
from users u
join channel_identities ci on ci.user_id = u.id
order by u.created_at;
