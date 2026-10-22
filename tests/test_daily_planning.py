"""Offline regressions for daily planning (no API key or dependencies required).

Run from the repository root: python -m unittest discover -s tests -v
"""

import contextlib
import datetime
import importlib.util
import io
from pathlib import Path
import random
import string
import sys
import types
import unittest
from unittest.mock import Mock, patch


BACKEND = Path(__file__).resolve().parents[1] / "reverie" / "backend_server"


def module_stub(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, BACKEND / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_planning_modules():
    # Isolate legacy wildcard imports and optional dependencies. The planning,
    # Scratch, prompt rendering, response validation and parsing code are real.
    stubs = {
        "global_methods": module_stub(
            "global_methods", random=random, string=string,
            check_if_file_exists=lambda path: False),
        "utils": module_stub("utils", debug=False, openai_api_key="unused"),
        "openai": module_stub("openai"),
        "persona.prompt_template.print_prompt": module_stub("print_prompt"),
        "persona.cognitive_modules.retrieve": module_stub(
            "retrieve", new_retrieve=Mock(return_value={})),
        "persona.cognitive_modules.converse": module_stub("converse"),
    }
    with patch.dict(sys.modules, stubs), patch.object(sys, "path", sys.path[:]):
        gpt = load_module("persona.prompt_template.gpt_structure",
                          "persona/prompt_template/gpt_structure.py")
        prompts = load_module("persona.prompt_template.run_gpt_prompt",
                              "persona/prompt_template/run_gpt_prompt.py")
        scratch = load_module("persona.memory_structures.scratch",
                              "persona/memory_structures/scratch.py")
        plan = load_module("persona.cognitive_modules.plan",
                           "persona/cognitive_modules/plan.py")
    # Templates are relative to the backend working directory in production.
    prompts.generate_prompt = lambda inputs, template: gpt.generate_prompt(
        inputs, str(BACKEND / template))
    return plan, prompts, gpt, scratch.Scratch


class DailyPlanningTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.prompts, self.gpt, scratch_class = load_planning_modules()
        scratch = scratch_class("unused.json")
        scratch.name = "Test Person"
        scratch.first_name = "Test"
        scratch.curr_time = datetime.datetime(2023, 2, 14)
        scratch.currently = "Yesterday's status"
        scratch.lifestyle = "Test wakes up early."
        scratch.daily_plan_req = "Keep the morning free."
        scratch.daily_req = ["yesterday's obsolete activity"]
        self.persona = types.SimpleNamespace(
            name=scratch.name, scratch=scratch,
            a_mem=types.SimpleNamespace(add_thought=Mock()))
        self.events = []
        self.daily_prompts = []
        self.hourly_prompts = []
        self.activity = "visit the library at 10:00 am"
        self.daily_response = None
        self.wake = self.enter_patch(self.plan, "generate_wake_up_hour",
                                    return_value=7)
        self.enter_patch(self.plan, "get_embedding", return_value=[0.1])
        self.request = self.enter_patch(self.gpt, "GPT_request",
                                       side_effect=self.respond)
        self.chat = self.enter_patch(self.plan, "ChatGPT_single_request")

    def enter_patch(self, target, name, **kwargs):
        patcher = patch.object(target, name, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def respond(self, prompt, parameters):
        if parameters["max_tokens"] == 500:
            self.events.append("daily")
            self.daily_prompts.append(prompt)
            if self.daily_response is not None:
                return self.daily_response
            # The prompt already supplies item 2's prefix; item 3 terminates it.
            return self.activity + ", 3) have lunch at noon."
        self.events.append("hourly")
        self.hourly_prompts.append(prompt)
        return "doing activity {}".format(len(self.hourly_prompts))

    def run_day(self, new_day, requirement="Attend the library meeting."):
        self.chat.side_effect = [
            "Remember the library meeting.", "Feeling prepared.",
            "Status: Ready for today's meeting.", requirement,
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            self.plan._long_term_planning(self.persona, new_day)

    def assert_consumers_use_current_plan(self):
        scratch = self.persona.scratch
        self.assertIsInstance(scratch.daily_req, list)
        self.assertTrue(all(isinstance(item, str) for item in scratch.daily_req))
        self.assertIsInstance(scratch.daily_plan_req, str)
        self.assertNotIn("yesterday's obsolete activity", scratch.daily_req)
        self.assertEqual(self.events[0], "daily")
        self.assertTrue(self.hourly_prompts)
        for prompt in self.hourly_prompts:
            for index, activity in enumerate(scratch.daily_req, 1):
                self.assertIn("{}) {}".format(index, activity), prompt)
            self.assertNotIn("yesterday's obsolete activity", prompt)
        thought = self.persona.a_mem.add_thought.call_args[0][5]
        for activity in scratch.daily_req:
            self.assertIn(activity, thought)
        self.assertNotIn("yesterday's obsolete activity", thought)
        self.assertEqual(sum(duration for _, duration in scratch.f_daily_schedule),
                         24 * 60)
        self.assertEqual(scratch.f_daily_schedule_hourly_org,
                         scratch.f_daily_schedule)
        self.assertIsNot(scratch.f_daily_schedule_hourly_org,
                         scratch.f_daily_schedule)

    def test_first_day_keeps_bootstrap_behavior(self):
        requirement = self.persona.scratch.daily_plan_req
        self.run_day("First day")
        self.chat.assert_not_called()
        self.wake.assert_called_once_with(self.persona)
        self.assertEqual(self.persona.scratch.daily_plan_req, requirement)
        self.assertEqual(len(self.daily_prompts), 1)
        self.assertIn(requirement, self.daily_prompts[0])
        self.assertEqual(self.persona.scratch.daily_req,
                         ["wake up and complete the morning routine at 7:00 am",
                          self.activity])
        self.assert_consumers_use_current_plan()

    def test_new_day_regenerates_from_revised_identity_before_hourly_schedule(self):
        previous = self.persona.scratch.daily_req
        requirement = "Attend the library meeting at 10:00 am."
        self.run_day("New day", requirement)
        self.assertEqual(self.chat.call_count, 4)
        self.assertEqual(len(self.daily_prompts), 1)
        self.assertIn(requirement, self.daily_prompts[0])
        self.assertIn("Status: Ready for today's meeting.", self.daily_prompts[0])
        self.assertIn(self.persona.scratch.get_str_curr_date_str(),
                      self.daily_prompts[0])
        self.assertIn("7:00 am", self.daily_prompts[0])
        self.assertEqual(self.persona.scratch.daily_plan_req, requirement)
        self.assertIsNot(self.persona.scratch.daily_req, previous)
        self.assertEqual(previous, ["yesterday's obsolete activity"])
        self.assertIn(self.activity, self.persona.scratch.daily_req)
        self.assert_consumers_use_current_plan()

    def test_consecutive_new_days_replace_previous_requirements(self):
        self.run_day("First day")
        for day, activity in [(15, "meet a friend at 2:00 pm"),
                              (16, "attend a class at 3:00 pm")]:
            with self.subTest(day=day):
                previous = self.persona.scratch.daily_req
                old_activity = self.activity
                self.activity = activity
                self.persona.scratch.curr_time = datetime.datetime(2023, 2, day)
                self.events.clear()
                self.daily_prompts.clear()
                self.hourly_prompts.clear()
                self.run_day("New day", "Today: " + activity)
                self.assertIsNot(self.persona.scratch.daily_req, previous)
                self.assertIn(activity, self.persona.scratch.daily_req)
                self.assertNotIn(old_activity, self.persona.scratch.daily_req)
                self.assertEqual(len(self.daily_prompts), 1)
                self.assertIn(self.persona.scratch.get_str_curr_date_str(),
                              self.daily_prompts[0])
                self.assert_consumers_use_current_plan()

    def test_new_day_preserves_list_contract_when_responses_are_invalid(self):
        self.daily_response = ""
        self.run_day("New day")
        self.assertEqual(len(self.daily_prompts), 5)
        self.assertIn("eat breakfast at 7:00 am", self.persona.scratch.daily_req)
        self.assert_consumers_use_current_plan()

    def test_generation_failure_does_not_schedule_or_store_stale_requirements(self):
        previous = self.persona.scratch.daily_req
        with patch.object(self.plan, "generate_first_daily_plan",
                          side_effect=RuntimeError("generation failed")):
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                self.run_day("New day")
        self.assertIs(self.persona.scratch.daily_req, previous)
        self.assertEqual(self.hourly_prompts, [])
        self.persona.a_mem.add_thought.assert_not_called()


if __name__ == "__main__":
    unittest.main()
