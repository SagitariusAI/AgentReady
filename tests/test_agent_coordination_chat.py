from __future__ import annotations

from typing import cast

from agent_coordination import chat


def test_publish_chat_calls_transport_with_agent_and_text():
    calls = []
    chat.publish_chat("claude", "hello team", transport=lambda a, t: calls.append((a, t)))
    assert calls == [("claude", "hello team")]


def test_publish_chat_never_raises_on_transport_failure():
    def boom(agent, text):
        raise RuntimeError("matrix down")
    # must not propagate -- coordination actions never break on a chat failure
    chat.publish_chat("claude", "x", transport=boom)  # no exception


def test_show_unread_returns_transport_output():
    assert chat.show_unread("/repo", transport=lambda repo: "[unread] 2 messages") == "[unread] 2 messages"


def test_show_unread_never_raises_returns_empty():
    def boom(repo):
        raise RuntimeError("comms down")
    assert chat.show_unread("/repo", transport=boom) == ""


def test_show_unread_none_output_becomes_empty_string():
    assert chat.show_unread("/repo", transport=lambda repo: cast(str, None)) == ""
