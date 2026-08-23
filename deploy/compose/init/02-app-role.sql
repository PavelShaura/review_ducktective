-- Роль приложения. Обычная, не суперпользователь — в этом весь смысл:
-- суперпользователь обходит row level security независимо от политик,
-- и под ним изоляция тенантов существует только на бумаге.
--
-- Таблицы создаёт и владеет ими эта же роль: политики объявлены
-- с `force row level security`, и на владельца они тоже действуют.
create role ducktective_app with login password 'ducktective_app'
    nosuperuser nocreatedb nocreaterole nobypassrls;

grant connect on database ducktective to ducktective_app;
grant all on schema public to ducktective_app;
alter schema public owner to ducktective_app;
