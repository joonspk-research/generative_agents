import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from translator import dashboard, social_network as social


class NetworkTests(SimpleTestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    previous = os.getcwd()
    os.chdir(self.temp.name)
    self.addCleanup(os.chdir, previous)
    social._cache.clear()
    self.names = ["Maya", "Rachel", "Elena"]
    self.folder = Path("storage/test/experiment")
    self.folder.mkdir(parents=True)

  def append(self, file, row, folder=None):
    with open((folder or self.folder) / file, "a") as f:
      f.write(json.dumps(row) + "\n")

  def convo(self, step, speakers=None, **extra):
    return {"step": step, "time": f"time-{step}",
            "speakers": speakers or ["Maya", "Rachel"],
            "utterances": [["Maya", f"line-{step}"], ["Rachel", "Reply"]], **extra}

  def opinion(self, step, score, category=None, **extra):
    return {"step": step, "time": f"time-{step}", "name": "Maya",
            "score": score, "category": category, "scale": 100,
            "scoring_version": "rubric_v1", **extra}

  def summary(self, step=1000, sim="test"):
    return social.network_summary(sim, self.names, step)

  def test_all_nodes_are_gray_without_measurements_or_conversations(self):
    r = self.summary()
    self.assertEqual([n["name"] for n in r["nodes"]], self.names)
    self.assertTrue(all(n["color"] == "#9299A4" for n in r["nodes"]))
    self.assertEqual(r["edges"], [])

  def test_more_than_300_and_repeated_pairs_accumulate(self):
    for i in range(1, 351):
      self.append("conversations.jsonl", self.convo(i))
    r = self.summary()
    self.assertEqual(len(r["edges"]), 1)
    self.assertEqual(r["edges"][0]["count"], 350)
    self.assertEqual(r["nodes"][0]["conversations"], 350)
    self.assertEqual(r["nodes"][0]["partners"], 1)
    self.assertEqual(r["edges"][0]["time"], "time-350")
    self.append("conversations.jsonl", self.convo(351, ["Rachel", "Maya"]))
    self.assertEqual(self.summary()["edges"][0]["count"], 351)

  def test_deduplication_invalid_pairs_and_multiple_speakers(self):
    row = self.convo(1)
    self.append("conversations.jsonl", row)
    self.append("conversations.jsonl", {**row, "speakers": ["Rachel", "Maya"],
                                        "summary": "changed summary"})
    self.append("conversations.jsonl", self.convo(2, ["Maya", "Maya"]))
    self.append("conversations.jsonl", self.convo(3, ["Unknown", "Maya"]))
    self.append("conversations.jsonl", self.convo(4, utterances=[]))
    self.append("conversations.jsonl", self.convo(5, completed=False))
    self.append("conversations.jsonl", self.convo(6, conversation_id="stable-id"))
    self.append("conversations.jsonl", self.convo(7, conversation_id="stable-id"))
    self.append("conversations.jsonl", self.convo(8, ["Maya", "Rachel", "Elena", "Unknown"]))
    r = self.summary()
    self.assertEqual(r["conversations"], 3)
    self.assertEqual([e["count"] for e in r["edges"]], [1, 1, 3])
    self.assertEqual(r["nodes"][0]["conversations"], 3)  # Group chat counts once.
    self.assertEqual(r["nodes"][0]["partners"], 2)

  def test_latest_valid_score_survives_null_and_invalid_records(self):
    for r in [self.opinion(1, 0, "very_strong_opposition"),
              self.opinion(2, 61, "moderate_support"), self.opinion(3, None),
              self.opinion(4, 100, "slight_support"), self.opinion(5, True)]:
      self.append("opinions.jsonl", r)
    n = self.summary()["nodes"][0]
    self.assertEqual((n["score"], n["color"], n["time"]), (61, "#48A276", "time-2"))
    self.assertEqual(self.summary(1)["nodes"][0]["score"], 0)
    self.assertIsNone(self.summary(0)["nodes"][0]["score"])

  def test_all_rubric_band_colors_at_both_boundaries(self):
    colors = ["#A32834", "#DD645D", "#EFAA86", "#D5B55C", "#A0CAA0", "#48A276", "#17754E"]
    step = 0
    for band, color in zip(social.BANDS, colors):
      for score in {band[1], band[2]}:
        step += 1
        self.append("opinions.jsonl", self.opinion(step, score, band[0]))
        node = self.summary()["nodes"][0]
        self.assertEqual((node["score"], node["category"], node["color"]),
                         (score, band[0], color))

  def test_legacy_color_is_visual_only_and_new_zero_is_valid(self):
    self.append("opinions.jsonl", {"step": 1, "name": "Maya", "score": 81, "scale": 100})
    n = self.summary()["nodes"][0]
    self.assertEqual(n["category"], "very_strong_support")
    self.assertEqual(n["scoring_version"], "legacy_direct")
    self.append("opinions.jsonl", {"step": 2, "name": "Maya", "score": 3})
    self.assertEqual(self.summary()["nodes"][0]["display_score"], 22)

  def test_fork_uses_copied_history_exactly_once_and_respects_saved_step(self):
    self.append("conversations.jsonl", self.convo(1))
    self.append("opinions.jsonl", self.opinion(1, 100, "very_strong_support"))
    shutil.copytree("storage/test", "storage/child")
    child = Path("storage/child/experiment")
    self.append("conversations.jsonl", self.convo(2), child)
    self.append("conversations.jsonl", self.convo(3))  # Later parent work isn't inherited.
    self.assertEqual(self.summary(sim="child")["edges"][0]["count"], 2)
    self.assertEqual(self.summary(1, "child")["edges"][0]["count"], 1)
    self.assertEqual(self.summary(1, "child")["nodes"][0]["score"], 100)
    social._cache.clear()  # Backend/frontend restart reconstructs identical data.
    self.assertEqual(self.summary(sim="child")["edges"][0]["count"], 2)

  def test_incremental_reads_partial_lines_truncation_and_replacement(self):
    self.append("conversations.jsonl", self.convo(1))
    first = self.summary()
    with patch("builtins.open", side_effect=AssertionError("unchanged log was reread")):
      self.assertIs(self.summary(), first)
    path = self.folder / "conversations.jsonl"
    with open(path, "a") as f:
      f.write(json.dumps(self.convo(2)))
    self.assertEqual(self.summary()["conversations"], 1)
    with open(path, "a") as f:
      f.write("\n")
    self.assertEqual(self.summary()["conversations"], 2)
    path.write_text("")
    self.assertEqual(self.summary()["conversations"], 0)
    self.append("conversations.jsonl", self.convo(1))
    self.assertEqual(self.summary()["conversations"], 1)
    replacement = self.folder / "replacement"
    replacement.write_text(json.dumps(self.convo(3)) + "\n")
    os.replace(replacement, path)
    self.assertEqual(self.summary()["edges"][0]["time"], "time-3")

  def test_live_and_saved_endpoints_use_full_history_and_step_cutoff(self):
    meta = Path("storage/test/reverie")
    meta.mkdir()
    (meta / "meta.json").write_text(json.dumps({"step": 350, "persona_names": self.names}))
    for i in range(1, 352):
      self.append("conversations.jsonl", self.convo(i))
    state_dir = Path("temp_storage/dashboard")
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text(json.dumps(
      {"step": 351, "sim_code": "test", "persona_order": self.names,
       "personas": {n: {"name": n} for n in self.names}}))
    with patch.object(dashboard, "_run_env", return_value="staging"):
      live = self.client.get("/dashboard/state/").json()
      saved = self.client.get("/dashboard/run/test/").json()
    self.assertEqual(len(live["conversations"]), 300)
    self.assertEqual(live["network"]["conversations"], 351)
    self.assertEqual(saved["network"]["conversations"], 350)
    self.assertEqual(len(saved["network"]["nodes"]), 3)

  def test_analysis_fields_stay_in_the_log_and_out_of_the_payload(self):
    # Every reading records the cosines and bands that chose its evidence, for
    # offline analysis. The graph needs the numbers, so neither that record nor
    # the node ids should be paid for on every poll.
    meta = Path("storage/test/reverie")
    meta.mkdir()
    (meta / "meta.json").write_text(json.dumps(
      {"step": 10, "persona_names": self.names}))
    self.append("opinions.jsonl", self.opinion(
      1, 61, "moderate_support", evidence=["node_1"],
      selection={"memories": [{"id": "node_1", "cos": 0.6, "band": "recent"}],
                 "bands": {"recent": 1, "mid": 0, "old": 0}}))
    saved = self.client.get("/dashboard/run/test/").json()
    row, = saved["opinions"]
    self.assertEqual((row["score"], row["category"]), (61, "moderate_support"))
    self.assertNotIn("selection", row)
    self.assertNotIn("evidence", row)
    logged = json.loads((self.folder / "opinions.jsonl").read_text())
    self.assertEqual(logged["selection"]["bands"]["recent"], 1)
