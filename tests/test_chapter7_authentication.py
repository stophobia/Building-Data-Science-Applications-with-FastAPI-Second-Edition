from collections.abc import AsyncGenerator
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from chapter7.authentication.app import app
from chapter7.authentication.database import get_async_session
from chapter7.authentication.models import AccessToken, Base, User
from chapter7.authentication.password import get_password_hash

DATABASE_FILE_PATH = "chapter7_authentication.test.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_FILE_PATH}"
engine = create_async_engine(DATABASE_URL)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_test_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture(autouse=True, scope="module")
async def initialize_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    initial_users = [
        User(
            id=1, email="user1@example.com", hashed_password=get_password_hash("foobar")
        )
    ]

    initial_tokens = [
        AccessToken(
            access_token="VALID_USER1_TOKEN",
            user_id=1,
            expiration_date=datetime.utcnow() + timedelta(seconds=86400),
        ),
        AccessToken(
            access_token="EXPIRED_USER1_TOKEN",
            user_id=1,
            expiration_date=datetime.utcnow() - timedelta(seconds=86400),
        ),
    ]

    async with async_session_maker() as session:
        for user in initial_users:
            session.add(user)
        for token in initial_tokens:
            session.add(token)
        await session.commit()

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.fastapi(
    app=app, dependency_overrides={get_async_session: get_test_async_session}
)
@pytest.mark.asyncio
class TestChapter7ProjectRegister:
    async def test_invalid_payload(self, client: httpx.AsyncClient):
        response = await client.post("/register", json={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_email_already_exists(self, client: httpx.AsyncClient):
        response = await client.post(
            "/register", json={"email": "user1@example.com", "password": "foobar"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        json = response.json()
        assert json["detail"] == "Email already exists"

    async def test_valid_payload(self, client: httpx.AsyncClient):
        response = await client.post(
            "/register", json={"email": "user2@example.com", "password": "foobar"}
        )

        assert response.status_code == status.HTTP_201_CREATED
        json = response.json()
        assert json["email"] == "user2@example.com"
        assert "id" in json
        assert "hashed_password" not in json


@pytest.mark.fastapi(
    app=app, dependency_overrides={get_async_session: get_test_async_session}
)
@pytest.mark.asyncio
class TestChapter7ProjectToken:
    async def test_invalid_payload(self, client: httpx.AsyncClient):
        response = await client.post("/token", data={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_invalid_email(self, client: httpx.AsyncClient):
        response = await client.post(
            "/token",
            data={"username": "user3@example.com", "password": "invalid_password"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_invalid_password(self, client: httpx.AsyncClient):
        response = await client.post(
            "/token",
            data={"username": "user1@example.com", "password": "invalid_password"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_valid_credentials(self, client: httpx.AsyncClient):
        response = await client.post(
            "/token",
            data={"username": "user1@example.com", "password": "foobar"},
        )

        assert response.status_code == status.HTTP_200_OK
        json = response.json()
        assert json["token_type"] == "bearer"
        assert "access_token" in json


@pytest.mark.fastapi(
    app=app, dependency_overrides={get_async_session: get_test_async_session}
)
@pytest.mark.asyncio
class TestChapter7ProjectProtectedRoute:
    async def test_not_authenticated(self, client: httpx.AsyncClient):
        response = await client.get("/protected-route")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_invalid_token(self, client: httpx.AsyncClient):
        response = await client.get(
            "/protected-route", headers={"Authorization": "Bearer INVALID_TOKEN"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_expired_token(self, client: httpx.AsyncClient):
        response = await client.get(
            "/protected-route", headers={"Authorization": "Bearer EXPIRED_USER1_TOKEN"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_valid_token(self, client: httpx.AsyncClient):
        response = await client.get(
            "/protected-route", headers={"Authorization": "Bearer VALID_USER1_TOKEN"}
        )

        assert response.status_code == status.HTTP_200_OK
        json = response.json()

        assert json == {"id": 1, "email": "user1@example.com"}
