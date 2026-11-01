from django.test import SimpleTestCase

import tempfile

from translator.dashboard import (_cost, _episodes, _is_reflection, _price,
                                  _run_env, _run_name)


class CostTests(SimpleTestCase):
  def test_prefix_match_prefers_longest(self):
    self.assertEqual(_price("gpt-4o-mini"), (0.15, 0.075, 0.60))
    self.assertEqual(_price("gpt-4o-2024-08-06"), (2.50, 1.25, 10.00))
    self.assertIsNone(_price("claude-sonnet-5-5"))

  def test_cached_tokens_billed_at_cached_rate(self):
    # 1M input of which 400k cached, plus 100k output, on gpt-4o:
    # 600k * 2.50 + 400k * 1.25 + 100k * 10.00 = 1.50 + 0.50 + 1.00
    row = {"model": "gpt-4o", "in": 1_000_000, "cached": 400_000, "out": 100_000}
    self.assertAlmostEqual(_cost(row), 3.00)

  def test_embedding_and_unpriced(self):
    self.assertAlmostEqual(_cost({"model": "text-embedding-3-small", "in": 1_000_000}), 0.02)
    self.assertIsNone(_cost({"model": "mystery-model", "in": 10}))


class RunEnvTests(SimpleTestCase):
  def env_of(self, text):
    with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
      f.write(text)
      f.flush()
      return _run_env(f.name)

  def test_reads_run_env_line(self):
    self.assertEqual(self.env_of('openai_api_key = "x"\nrun_env = "staging"\n'), "staging")
    self.assertEqual(self.env_of("run_env='production'\n"), "production")

  def test_defaults_to_staging(self):
    self.assertEqual(self.env_of('chat_model = "gpt-4o"\n'), "staging")
    self.assertEqual(self.env_of('# run_env = "production"\n'), "staging")
    self.assertEqual(_run_env("/nonexistent/utils.py"), "staging")

  def test_names_get_their_mode_prefix_once(self):
    self.assertEqual(_run_name("run-1", "staging"), "stg-run-1")
    self.assertEqual(_run_name("stg-run-1", "staging"), "stg-run-1")
    self.assertEqual(_run_name("run-1", "production"), "prod-run-1")
    self.assertEqual(_run_name("prod-run-1", "production"), "prod-run-1")

  def test_other_mode_prefix_is_swapped(self):
    self.assertEqual(_run_name("prod-run-1", "staging"), "stg-run-1")
    self.assertEqual(_run_name("stg-run-1", "production"), "prod-run-1")


class ReflectionTests(SimpleTestCase):
  """Telling a reflection insight apart from an ordinary thought.

  Nothing marks a reflection at write time, so the Mind tab infers it from what
  the thought cites as evidence. The cases below are the ones that actually
  occur in saved runs; check_memory_categories.py runs the same table through
  the live-run copy of this rule in dashboard_bridge.py.
  """

  BY_ID = {
    "node_1": {"type": "event", "created": "2023-02-13 09:00:00"},
    "node_2": {"type": "thought", "created": "2023-02-13 09:10:00"},
    "node_3": {"type": "chat", "created": "2023-02-13 09:20:00"},
  }

  def is_reflection(self, **node):
    return _is_reflection({"type": "thought", **node}, self.BY_ID)

  def test_evidence_of_events_only_is_a_reflection(self):
    # Depth 1, exactly like a daily plan: a depth test would miss this one.
    self.assertTrue(self.is_reflection(filling=["node_1"]))

  def test_evidence_of_thoughts_is_a_reflection(self):
    self.assertTrue(self.is_reflection(filling=["node_1", "node_2"]))

  def test_a_thought_citing_a_chat_is_not(self):
    # The two thoughts written after a conversation. Insight evidence comes from
    # new_retrieve, which never returns a chat, so a chat rules a reflection out.
    self.assertFalse(self.is_reflection(filling=["node_3"]))
    self.assertFalse(self.is_reflection(filling=["node_1", "node_3"]))

  def test_evidence_that_does_not_resolve_is_not(self):
    # A plan or a whisper carries no node ids at all; and the insight prompt has
    # a fallback that can write the string "node_1" where a list belongs.
    self.assertFalse(self.is_reflection(filling=None))
    self.assertFalse(self.is_reflection(filling=[]))
    self.assertFalse(self.is_reflection(filling="node_1"))
    self.assertFalse(self.is_reflection(filling=["node_99"]))

  def test_only_thoughts_can_be_reflections(self):
    self.assertFalse(_is_reflection({"type": "event", "filling": ["node_1"]}, self.BY_ID))

  def test_episodes_are_distinct_timestamps_in_order(self):
    # One reflection writes several insights at one timestamp, so the Mind tab
    # counts and cuts by timestamp rather than by row.
    nodes = [{"created": "09:35"}, {"created": "09:35"}, {"created": "08:10"},
             {"created": "09:35"}]
    self.assertEqual(_episodes(nodes), ["09:35", "08:10"])
    self.assertEqual(_episodes([]), [])
