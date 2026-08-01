"""Alembicの実行環境。

接続先は alembic.ini ではなく config.DATABASE_URL(= .env)から取る。
設定の出どころをアプリと一本化し、iniに秘密を書かずに済ませるため。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# backend/ から実行する前提(alembic.ini の prepend_sys_path = . で解決される)
import config as app_config
from db import metadata

alembic_config = context.config
# アプリから programmatic に呼ぶときは configure_logger=False が渡るので、
# アプリ側のログ設定をalembicのiniで上書きしない
if alembic_config.config_file_name is not None and alembic_config.attributes.get(
    "configure_logger", True
):
    fileConfig(alembic_config.config_file_name)

alembic_config.set_main_option("sqlalchemy.url", app_config.DATABASE_URL)

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=app_config.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
