from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

from database import create_database_engine
from models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_database_engine().execution_options(isolation_level="AUTOCOMMIT")

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, poolclass=pool.NullPool)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()