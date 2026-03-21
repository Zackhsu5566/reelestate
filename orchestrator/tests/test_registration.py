import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from orchestrator.line.conversation import ConversationState


@pytest.fixture
def mock_deps():
    """Set up all mock dependencies for webhook handlers."""
    bot = AsyncMock()
    conv = AsyncMock()
    user_store = AsyncMock()
    return bot, conv, user_store


@pytest.mark.asyncio
async def test_new_user_starts_registration(mock_deps):
    """New user (no profile) should enter registering_name.

    Note: This tests the webhook module's _handle_text function.
    Module-level singletons (line_bot, conv_manager, user_store) must be
    patched at module level.
    """
    bot, conv, user_store = mock_deps
    user_store.get.return_value = None  # no profile
    conv.get.return_value = {"state": ConversationState.idle}

    with patch("orchestrator.line.webhook.user_store", user_store), \
         patch("orchestrator.line.webhook.conv_manager", conv), \
         patch("orchestrator.line.webhook.line_bot", bot):
        from orchestrator.line.webhook import _handle_text
        await _handle_text("U123", "hello")

    conv.start_registration.assert_called_once_with("U123")
    bot.send_registration_name_prompt.assert_called_once_with("U123")


@pytest.mark.asyncio
async def test_registering_name_valid(mock_deps):
    """Valid name should advance to registering_company."""
    bot, conv, user_store = mock_deps
    user_store.get.return_value = None
    conv.get.return_value = {"state": ConversationState.registering_name}

    from orchestrator.line.webhook import _handle_registration
    await _handle_registration("U123", "王小明", ConversationState.registering_name,
                                bot, conv)

    conv.set_reg_field.assert_called_once_with(
        "U123", "reg_name", "王小明", ConversationState.registering_company,
    )
    bot.send_registration_company_prompt.assert_called_once()


@pytest.mark.asyncio
async def test_registering_name_invalid(mock_deps):
    """Invalid name should show error, not advance."""
    bot, conv, user_store = mock_deps
    conv.get.return_value = {"state": ConversationState.registering_name}

    from orchestrator.line.webhook import _handle_registration
    await _handle_registration("U123", "", ConversationState.registering_name,
                                bot, conv)

    conv.set_reg_field.assert_not_called()
    bot.send_validation_error.assert_called_once()
