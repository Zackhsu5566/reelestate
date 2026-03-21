import pytest
from unittest.mock import AsyncMock
from orchestrator.stores.user import UserStore
from orchestrator.models import UserProfile


@pytest.fixture
def mock_redis():
    _hash_store: dict[str, dict[str, str]] = {}

    r = AsyncMock()

    async def _hset(key, mapping=None):
        if key not in _hash_store:
            _hash_store[key] = {}
        _hash_store[key].update({k: str(v) for k, v in mapping.items()})

    async def _hgetall(key):
        return _hash_store.get(key, {})

    async def _eval(script, num_keys, *args):
        # 簡易模擬 Lua script
        key = args[0]
        data = _hash_store.get(key, {})
        usage = int(data.get("usage", "0"))
        quota = int(data.get("quota", "3"))
        if usage < quota:
            data["usage"] = str(usage + 1)
            return 1
        return 0

    r.hset = AsyncMock(side_effect=_hset)
    r.hgetall = AsyncMock(side_effect=_hgetall)
    r.eval = AsyncMock(side_effect=_eval)
    return r, _hash_store


@pytest.fixture
def store(mock_redis):
    r, _ = mock_redis
    return UserStore(r)


@pytest.mark.asyncio
async def test_create_and_get(store, mock_redis):
    profile = UserProfile(
        line_user_id="U123",
        name="王小明",
        company="信義房屋",
        phone="0912345678",
        created_at="2026-03-21T10:00:00",
    )
    await store.create(profile)
    result = await store.get("U123")
    assert result is not None
    assert result.name == "王小明"
    assert result.quota == 3
    assert result.usage == 0


@pytest.mark.asyncio
async def test_get_nonexistent(store):
    result = await store.get("NONEXIST")
    assert result is None


@pytest.mark.asyncio
async def test_try_consume_quota_success(store, mock_redis):
    _, hash_store = mock_redis
    hash_store["user:U123"] = {
        "line_user_id": "U123", "name": "Test", "company": "Co",
        "phone": "0912345678", "plan": "premium",
        "quota": "3", "usage": "0", "created_at": "2026-03-21T10:00:00",
    }
    assert await store.try_consume_quota("U123") is True


@pytest.mark.asyncio
async def test_try_consume_quota_exceeded(store, mock_redis):
    _, hash_store = mock_redis
    hash_store["user:U123"] = {
        "line_user_id": "U123", "name": "Test", "company": "Co",
        "phone": "0912345678", "plan": "premium",
        "quota": "3", "usage": "3", "created_at": "2026-03-21T10:00:00",
    }
    assert await store.try_consume_quota("U123") is False


@pytest.mark.asyncio
async def test_update_preserves_other_fields(store, mock_redis):
    _, hash_store = mock_redis
    hash_store["user:U123"] = {
        "line_user_id": "U123", "name": "Old", "company": "Co",
        "phone": "0912345678", "plan": "premium", "line_id": "",
        "quota": "3", "usage": "2", "created_at": "2026-03-21T10:00:00",
    }
    await store.update("U123", name="New Name", company="New Co")
    result = await store.get("U123")
    assert result.name == "New Name"
    assert result.usage == 2  # preserved
