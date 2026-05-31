import os
from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine
from cobol_modernizer.persistence.tables import Base

# Honor .env so `alembic upgrade head` picks up POSTGRES_URL without exporting it.
load_dotenv()

target_metadata = Base.metadata

def run_migrations_online():
    url = os.environ["POSTGRES_URL"]
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
