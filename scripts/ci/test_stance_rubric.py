"""Rubric contract and observer regression tests. No external API calls."""
import datetime
import json
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                      "reverie", "backend_server"))
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

import opinion_probe
from persona.prompt_template import gpt_structure, run_gpt_prompt as prompts
import reverie


class RubricTests(unittest.TestCase):
  def setUp(self):
    quiet = patch.object(prompts, "debug", False)
    quiet.start()
    self.addCleanup(quiet.stop)

  def rating(self, score=50, category="neutral_mixed", **extra):
    return {"category": category, "score": score,
            "rationale": "The agent explicitly states a balanced view.", **extra}

  def persona(self):
    return NS(scratch=NS(name="Rachel Nguyen", age=36,
                        curr_time=datetime.datetime(2023, 2, 13, 12),
                        f_daily_schedule=[],
                        act_description="working"))

  def test_all_band_boundaries(self):
    expected = [(0, 19, "very_strong_opposition"),
                (20, 39, "moderate_opposition"), (40, 49, "slight_opposition"),
                (50, 50, "neutral_mixed"), (51, 60, "slight_support"),
                (61, 80, "moderate_support"), (81, 100, "very_strong_support")]
    for low, high, category in expected:
      for score in {low, high}:
        with self.subTest(score=score):
          r = prompts.parse_rubric_stance(self.rating(score, category))
          self.assertEqual((r["score"], r["category"]), (score, category))
          self.assertEqual(r["scoring_version"], "rubric_v1")

  def test_runtime_prompt_uses_the_exact_validated_bands(self):
    with patch.object(gpt_structure, "ChatGPT_request",
                      return_value=json.dumps({"output": self.rating()})):
      _, diagnostics = prompts.run_gpt_prompt_datacenter_stance(self.persona(), "evidence")
    prompt_path, text = "persona/prompt_template/v3_ChatGPT/datacenter_stance_rubric_v1.txt", diagnostics[1]
    self.assertTrue(os.path.isfile(prompt_path))
    for category, low, high in prompts.STANCE_BANDS:
      band = f"{low}-{high}" if low != high else f"{low} only"
      self.assertIn(f"{category}: {band}", text)
    self.assertIn("CURRENT FORM", text)

  def test_rejects_invalid_and_inconsistent_outputs(self):
    invalid = [self.rating(s) for s in [-1, 101, True, 50.0, "50", float("nan")]]
    invalid += [self.rating(51), self.rating(50, "neutral"), self.rating(None),
                self.rating(category=None), self.rating(rationale=""),
                self.rating(conditions="local hiring"), self.rating(conditions=[1]),
                {}, "nonsense", [50], None]
    for r in invalid:
      with self.subTest(response=r), self.assertRaises((ValueError, TypeError)):
        prompts.parse_rubric_stance(r)

  def test_fenced_structured_json_and_conditions(self):
    raw = self.rating(61, "moderate_support", conditions=["Enforce local hiring"])
    r = prompts.parse_rubric_stance("```json\n" + json.dumps(raw) + "\n```")
    self.assertEqual(r["conditions"], raw["conditions"])

  def call_model(self, responses):
    with patch.object(gpt_structure, "ChatGPT_request", side_effect=responses) as api:
      r = prompts.run_gpt_prompt_datacenter_stance(
        self.persona(), 'Rachel Nguyen said: "I am genuinely torn."',
        with_metadata=True)
    return r, api

  def test_abstention_is_valid_and_never_becomes_fifty(self):
    (r, _), api = self.call_model([json.dumps({"output": self.rating(None, None)})])
    self.assertIsNone(r["score"])
    self.assertIsNone(r["category"])
    self.assertEqual(r["withheld"], "abstained")
    self.assertEqual(api.call_count, 1)

  def test_invalid_retries_and_failure_becomes_null(self):
    (r, _), api = self.call_model(["invalid"] * 3)
    self.assertIsNone(r["score"])
    self.assertEqual(r["withheld"], "evaluator_invalid")
    self.assertEqual(api.call_count, 3)
    (r, _), api = self.call_model([json.dumps({"output": self.rating(51)}),
                                  json.dumps({"output": self.rating()})])
    self.assertEqual(r["score"], 50)
    self.assertEqual(api.call_count, 2)
    self.assertEqual(api.call_args.args[1], 0)

  def test_legacy_consumer_shape_is_preserved(self):
    with patch.object(gpt_structure, "ChatGPT_request",
                      return_value=json.dumps({"output": self.rating()})):
      value, _ = prompts.run_gpt_prompt_datacenter_stance(self.persona(), "evidence")
    self.assertEqual(value, (50, self.rating()["rationale"]))

  def test_no_api_for_asleep_or_empty_memory(self):
    p = self.persona()
    p.a_mem = NS(seq_event=[], seq_thought=[], seq_chat=[], embeddings={})
    with patch.object(opinion_probe, "pool_relevance") as relevance:
      # 12:00, so a sleeping agent is a planner defect rather than a night.
      for action, reason in [("sleeping", "asleep_daytime"),
                             ("working", "no_memory")]:
        p.scratch.act_description = action
        r = opinion_probe.probe(p, with_metadata=True)
        self.assertIsNone(r["score"])
        self.assertEqual(r["withheld"], reason)
        self.assertEqual(r["scoring_version"], "rubric_v1")
      relevance.assert_not_called()

  def test_only_idle_records_are_also_unmeasurable(self):
    p = self.persona()
    p.a_mem = NS(seq_event=[NS(embedding_key="table is idle")], seq_thought=[])
    with patch.object(opinion_probe, "pool_relevance") as relevance:
      r = opinion_probe.probe(p, with_metadata=True)
    self.assertIsNone(r["score"])
    self.assertEqual(r["withheld"], "no_memory")
    relevance.assert_not_called()

  def test_evidence_is_read_only_attributed_filtered_and_chronological(self):
    p = self.persona()
    now = p.scratch.curr_time
    good = NS(node_id="good", created=now, last_accessed=now,
              embedding_key="a water concern")
    bad = NS(node_id="bad", created=now, last_accessed=now,
             embedding_key="breakfast")
    p.a_mem = NS(seq_event=[good, bad], seq_thought=[], embeddings={})
    utterance = (now - datetime.timedelta(hours=1), "I oppose the current proposal")
    rated = prompts.parse_rubric_stance(self.rating(19, "very_strong_opposition"))
    with patch.object(opinion_probe, "own_utterances", return_value=[utterance]), \
         patch.object(opinion_probe, "select_utterances", return_value=[utterance]), \
         patch.object(opinion_probe, "embed", return_value=[1.0, 0.0]), \
         patch.object(opinion_probe, "pool_relevance", return_value={"good": .8, "bad": .2}), \
         patch.object(opinion_probe, "run_gpt_prompt_datacenter_stance",
                      return_value=(rated, [])) as model:
      r = opinion_probe.probe(p, with_metadata=True)
      # Read-only, held more simply than touch=False now that the probe
      # selects its own evidence: the only write to last_accessed is inside
      # new_retrieve, and the probe no longer reaches it at all.
      self.assertEqual([n.last_accessed for n in p.a_mem.seq_event], [now, now])
      text = model.call_args.args[1]
      self.assertIn('Rachel Nguyen said: "I oppose the current proposal"', text)
      self.assertLess(text.index("said:"), text.index("a water concern"))
      self.assertNotIn("breakfast", text)
      self.assertEqual(r["evidence"], ["good"])
      self.assertEqual(r["quoted"]["n"], 1)
      self.assertEqual(p.a_mem.embeddings, {})

  def test_selection_records_the_cosines_that_chose_the_evidence(self):
    p = self.persona()
    now = p.scratch.curr_time
    shown = NS(node_id="shown", created=now, embedding_key="a water concern")
    missed = NS(node_id="missed", created=now, embedding_key="breakfast")
    rated = prompts.parse_rubric_stance(self.rating())
    p.a_mem = NS(seq_event=[shown, missed], seq_thought=[], embeddings={})
    with patch.object(opinion_probe, "own_utterances", return_value=[]), \
         patch.object(opinion_probe, "select_utterances", return_value=[]), \
         patch.object(opinion_probe, "embed", return_value=[1.0, 0.0]), \
         patch.object(opinion_probe, "pool_relevance",
                      return_value={"shown": .8, "missed": .2}), \
         patch.object(opinion_probe, "run_gpt_prompt_datacenter_stance",
                      return_value=(rated, [])):
      r = opinion_probe.probe(p, with_metadata=True)
    self.assertEqual(r["selection"]["memories"],
                     [{"id": "shown", "cos": .8, "band": "recent",
                       "created": now.strftime("%Y-%m-%d %H:%M:%S")}])
    self.assertEqual(r["selection"]["rejected"],
                     [{"id": "missed", "cos": .2, "reason": "below_floor"}])
    self.assertEqual(r["selection"]["bands"], {"recent": 1, "mid": 0, "old": 0})

  def test_no_relevant_memory_abstains_before_model(self):
    p = self.persona()
    p.a_mem = NS(seq_event=[NS(node_id="x", created=p.scratch.curr_time,
                               embedding_key="breakfast")], seq_thought=[])
    with patch.object(opinion_probe, "own_utterances", return_value=[]), \
         patch.object(opinion_probe, "select_utterances", return_value=[]), \
         patch.object(opinion_probe, "embed", return_value=[1.0, 0.0]), \
         patch.object(opinion_probe, "pool_relevance", return_value={"x": .2}), \
         patch.object(opinion_probe, "run_gpt_prompt_datacenter_stance") as model:
      r = opinion_probe.probe(p, with_metadata=True)
      self.assertIsNone(r["score"])
      self.assertEqual(r["withheld"], "no_relevant_memory")
      # The rationale quotes <best>, which is only true now that the pool's
      # closest memory cannot be crowded out of the prompt.
      self.assertIn("0.20", r["rationale"])
      self.assertEqual(r["selection"]["rejected"][0]["reason"], "below_floor")
      model.assert_not_called()

  def node(self, node_id, hours_old, now):
    return NS(node_id=node_id, embedding_key=f"key {node_id}",
              created=now - datetime.timedelta(hours=hours_old))

  def test_bands_hold_slots_for_the_past_and_give_back_what_they_cannot_fill(self):
    now = datetime.datetime(2023, 2, 16, 12)
    # Twelve candidates in the recent band against its quota of eight, all at
    # distinct timestamps so the per-timestamp cap is not what binds, plus one
    # lone memory from two days earlier.
    recent = [self.node(f"r{i}", i * 0.5, now) for i in range(12)]
    old = self.node("old", 48, now)
    kept, rejected, bands = opinion_probe.allocate(recent + [old], now, 20)
    # The old memory keeps its reserved slot even though eleven recent ones
    # outrank it, and the mid band's seven unfilled slots go back to recent --
    # which the band counts report as the twelve slots recent really used, not
    # the eight it was promised.
    self.assertIn(old, kept)
    self.assertEqual(len(kept), 13)
    self.assertEqual(rejected, [])
    self.assertEqual(bands, {"recent": 12, "mid": 0, "old": 1})

    # Nothing can be evicted by banding when the budget is the binding limit.
    kept, rejected, _ = opinion_probe.allocate(recent + [old], now, 3)
    self.assertEqual([n.node_id for n in kept], ["r0", "r1", "r2"])
    self.assertEqual({reason for _, reason in rejected}, {"budget_full"})

  def test_one_timestamp_cannot_crowd_a_band(self):
    now = datetime.datetime(2023, 2, 16, 12)
    burst = [self.node(f"b{i}", 1, now) for i in range(6)]
    kept, rejected, _ = opinion_probe.allocate(burst, now, 20)
    self.assertEqual(len(kept), opinion_probe.PER_TIMESTAMP_N)
    self.assertEqual({reason for _, reason in rejected}, {"timestamp_cap"})

  def test_quotes_reserve_the_latest_conversation_and_keep_dialogue_order(self):
    now = datetime.datetime(2023, 2, 16, 12)
    latest, earlier = now - datetime.timedelta(hours=1), now - datetime.timedelta(days=1)
    # own_utterances emits newest conversation first, dialogue order within.
    utterances = [(latest, "and the water figure worries me"),
                  (latest, "so I asked about the cooling load"),
                  (earlier, "the datacenter proposal is the only thing anyone "
                            "talks about")]
    with patch.object(opinion_probe, "embed", return_value=[1.0, 0.0]):
      chosen = opinion_probe.select_utterances(utterances, 10)
    # Oldest first for the prompt, but the latest pair stays in the order it
    # was spoken rather than being reordered by cosine.
    self.assertEqual([line for _, line in chosen],
                     [utterances[2][1], utterances[0][1], utterances[1][1]])

    # With only the recent slots to give, the latest conversation takes them.
    with patch.object(opinion_probe, "embed", return_value=[1.0, 0.0]):
      chosen = opinion_probe.select_utterances(utterances, 2)
    self.assertEqual([line for _, line in chosen],
                     [utterances[0][1], utterances[1][1]])
    self.assertEqual(opinion_probe.select_utterances([], 10), [])

  def sleeper(self, schedule, hour=7):
    """A persona whose schedule index resolves the way scratch.py's does."""
    p = self.persona()
    p.scratch.curr_time = datetime.datetime(2023, 2, 16, hour)
    p.scratch.act_description = "sleeping"
    p.scratch.f_daily_schedule = schedule

    def index(advance=0):
      minutes = p.scratch.curr_time.hour * 60 + advance
      elapsed = 0
      for i, (_, duration) in enumerate(schedule):
        elapsed += duration
        if elapsed > minutes:
          return i
      return len(schedule)

    p.scratch.get_f_daily_schedule_index = index
    return p

  def test_sleep_is_judged_over_the_hour_not_the_instant(self):
    # 7:00, on a day whose sleep runs to 7:20. Asleep at the instant the probe
    # fires, awake twenty minutes later -- 28 of 177 asleep withholdings over
    # a measured game day were this, the probe sampling the top of the hour
    # before the waking action had been installed.
    waking = self.sleeper([["sleeping", 440], ["waking up", 40],
                           ["having breakfast", 60]])
    self.assertFalse(opinion_probe.is_asleep(waking))

    # A whole hour of sleep is still withheld, and labelled by the clock: 7am
    # sleep is the planner defect the split label exists to expose, 3am is not.
    through = self.sleeper([["sleeping", 600]])
    self.assertTrue(opinion_probe.is_asleep(through))
    self.assertEqual(opinion_probe.asleep_reason(through.scratch.curr_time),
                     "asleep_daytime")
    night = self.sleeper([["sleeping", 600]], hour=3)
    self.assertTrue(opinion_probe.is_asleep(night))
    self.assertEqual(opinion_probe.asleep_reason(night.scratch.curr_time),
                     "asleep_night")

    # Before the first plan exists there is no schedule to read.
    bootstrap = self.sleeper([])
    self.assertTrue(opinion_probe.is_asleep(bootstrap))
    bootstrap.scratch.act_description = "working"
    self.assertFalse(opinion_probe.is_asleep(bootstrap))

  def test_logged_record_preserves_old_metadata_and_adds_rubric_fields(self):
    p = self.persona()
    server = reverie.ReverieServer.__new__(reverie.ReverieServer)
    server.personas = {p.scratch.name: p}
    server.step, server.curr_time = 360, p.scratch.curr_time
    from unittest.mock import Mock
    server.experiment_logger = Mock()
    reading = {**prompts.parse_rubric_stance(self.rating(0, "very_strong_opposition")),
               "evidence": ["node_1"], "relevance": {"shown": .8, "best": .9},
               "quoted": {"n": 1, "first": "earlier", "last": "now"}}
    with patch.object(reverie, "probe_opinion", return_value=reading):
      server.probe_opinions()
    row = server.experiment_logger.log_opinions.call_args.args[2][0]
    self.assertEqual(row["score"], 0)
    self.assertEqual(row["scoring_version"], "rubric_v1")
    self.assertEqual(row["evidence"], ["node_1"])
    self.assertEqual(row["quoted"]["n"], 1)
    self.assertTrue({"name", "model", "run_env", "withheld", "conditions"} <= row.keys())


if __name__ == "__main__":
  unittest.main()
