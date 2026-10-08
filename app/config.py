from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Read from environment variables (POSTGRES_HOST, ELASTICSEARCH_URL, ...)."""

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "documents"
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "documents"
    csv_path: str = "posts.csv"

    @property
    def postgres(self) -> dict:
        """Connection arguments for asyncpg.connect() / asyncpg.create_pool()."""
        return {
            "host": self.postgres_host,
            "port": self.postgres_port,
            "user": self.postgres_user,
            "password": self.postgres_password,
            "database": self.postgres_db,
        }
