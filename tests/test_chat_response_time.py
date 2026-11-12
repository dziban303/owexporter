"""Regression checks for response-time estimates from stored chats."""

import unittest
from unittest.mock import patch

from collectors import chats
from metrics import CHAT_AVG_RESPONSE_SECONDS


class ChatResponseTimeTests(unittest.TestCase):
    def test_cutoff_applies_only_to_timestamp_estimates(self):
        def reply(timestamp, model="test-model", usage=None):
            return {
                "role": "assistant",
                "parentId": "prompt",
                "model": model,
                "timestamp": timestamp,
                "usage": usage,
            }

        messages = {
            "prompt": {"role": "user", "timestamp": 100},
            "quick": reply(110),
            "at-limit": reply(1300),
            "over-limit": reply(1301),
            "reported": reply(5000, usage={"total_duration": 1800 * 10**9}),
            "outlier-only": reply(5000, model="outlier-only"),
        }
        self.addCleanup(CHAT_AVG_RESPONSE_SECONDS.clear)
        with patch.object(
            chats, "get_json", return_value=[{"chat": {"history": {"messages": messages}}}]
        ):
            chats.collect_chats_stats(None, "http://example")

        samples = {
            sample.labels["model"]: sample.value
            for metric in CHAT_AVG_RESPONSE_SECONDS.collect()
            for sample in metric.samples
        }
        self.assertEqual(samples, {"test-model": (10 + 1200 + 1800) / 3})
