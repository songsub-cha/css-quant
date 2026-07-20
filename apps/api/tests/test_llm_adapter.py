import asyncio

from src.adapters.llm import FakeLLMClient


def test_fake_llm_client_is_deterministic() -> None:
    client = FakeLLMClient()

    first = asyncio.run(client.complete("score this stock"))
    second = asyncio.run(client.complete("score this stock"))

    assert first == second


def test_fake_llm_client_varies_by_prompt() -> None:
    client = FakeLLMClient()

    a = asyncio.run(client.complete("prompt a"))
    b = asyncio.run(client.complete("prompt b"))

    assert a != b
