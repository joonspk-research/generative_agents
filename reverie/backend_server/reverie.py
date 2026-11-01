"""
Author: Joon Sung Park (joonspk@stanford.edu)

File: reverie.py
Description: This is the main program for running generative agent simulations
that defines the ReverieServer class. This class maintains and records all  
states related to the simulation. The primary mode of interaction for those  
running the simulation should be through the open_server function, which  
enables the simulator to input command-line prompts for running and saving  
the simulation, among other tasks.

Release note (June 14, 2023) -- Reverie implements the core simulation 
mechanism described in my paper entitled "Generative Agents: Interactive 
Simulacra of Human Behavior." If you are reading through these lines after 
having read the paper, you might notice that I use older terms to describe 
generative agents and their cognitive modules here. Most notably, I use the 
term "personas" to refer to generative agents, "associative memory" to refer 
to the memory stream, and "reverie" to refer to the overarching simulation 
framework.
"""
import json
import numpy
import datetime
import pickle
import time
import math
import os
import shutil
import sys
import traceback

from selenium import webdriver

from global_methods import *
from utils import *
from maze import *
from persona.persona import *
from experiment_logger import ExperimentLogger, set_experiment_logger, get_experiment_logger
from opinion_probe import probe as probe_opinion, STANCE_SCALE
from sim_logging import get_logger, setup_logging
from dashboard_bridge import CommandFeed, record_result, write_state, load_settings
from llm import usage
import run_env

log = get_logger("reverie")


def _write_json_atomic(path, obj): 
  # Readers (the frontend, the next loop pass) never see a half-written file.
  tmp = f"{path}.tmp"
  with open(tmp, "w") as outfile: 
    outfile.write(json.dumps(obj, indent=2))
  os.replace(tmp, path)


##############################################################################
#                                  REVERIE                                   #
##############################################################################

class ReverieServer: 
  def __init__(self, 
               fork_sim_code,
               sim_code):
    setup_logging()
    log.info("Forking simulation: fork=%s -> sim=%s", fork_sim_code, sim_code)
    # FORKING FROM A PRIOR SIMULATION:
    # <fork_sim_code> indicates the simulation we are forking from. 
    # Interestingly, all simulations must be forked from some initial 
    # simulation, where the first simulation is "hand-crafted".
    self.fork_sim_code = fork_sim_code
    fork_folder = f"{fs_storage}/{self.fork_sim_code}"

    # <sim_code> indicates our current simulation. The first step here is to 
    # copy everything that's in <fork_sim_code>, but edit its 
    # reverie/meta/json's fork variable. 
    self.sim_code = sim_code
    usage.context["sim"] = sim_code
    sim_folder = f"{fs_storage}/{self.sim_code}"
    copyanything(fork_folder, sim_folder)
    # Git does not track empty dirs, so base sims ship without movement/.
    os.makedirs(f"{sim_folder}/movement", exist_ok=True)
    log.info("Copied storage folder to %s", sim_folder)

    with open(f"{sim_folder}/reverie/meta.json") as json_file:  
      reverie_meta = json.load(json_file)

    with open(f"{sim_folder}/reverie/meta.json", "w") as outfile: 
      reverie_meta["fork_sim_code"] = fork_sim_code
      outfile.write(json.dumps(reverie_meta, indent=2))

    # LOADING REVERIE'S GLOBAL VARIABLES
    # The start datetime of the Reverie: 
    # <start_datetime> is the datetime instance for the start datetime of 
    # the Reverie instance. Once it is set, this is not really meant to 
    # change. It takes a string date in the following example form: 
    # "June 25, 2022"
    # e.g., ...strptime(June 25, 2022, "%B %d, %Y")
    self.start_time = datetime.datetime.strptime(
                        f"{reverie_meta['start_date']}, 00:00:00",  
                        "%B %d, %Y, %H:%M:%S")
    # <curr_time> is the datetime instance that indicates the game's current
    # time. This gets incremented by <sec_per_step> amount everytime the world
    # progresses (that is, everytime curr_env_file is recieved). 
    self.curr_time = datetime.datetime.strptime(reverie_meta['curr_time'], 
                                                "%B %d, %Y, %H:%M:%S")
    # <sec_per_step> denotes the number of seconds in game time that each 
    # step moves foward. 
    self.sec_per_step = reverie_meta['sec_per_step']
    
    # <maze> is the main Maze instance. Note that we pass in the maze_name
    # (e.g., "double_studio") to instantiate Maze. 
    # e.g., Maze("double_studio")
    self.maze = Maze(reverie_meta['maze_name'])
    
    # <step> denotes the number of steps that our game has taken. A step here
    # literally translates to the number of moves our personas made in terms
    # of the number of tiles. 
    self.step = reverie_meta['step']

    # SETTING UP PERSONAS IN REVERIE
    # <personas> is a dictionary that takes the persona's full name as its 
    # keys, and the actual persona instance as its values.
    # This dictionary is meant to keep track of all personas who are part of
    # the Reverie instance. 
    # e.g., ["Isabella Rodriguez"] = Persona("Isabella Rodriguezs")
    self.personas = dict()
    # <personas_tile> is a dictionary that contains the tile location of
    # the personas (!-> NOT px tile, but the actual tile coordinate).
    # The tile take the form of a set, (row, col). 
    # e.g., ["Isabella Rodriguez"] = (58, 39)
    self.personas_tile = dict()
    
    # # <persona_convo_match> is a dictionary that describes which of the two
    # # personas are talking to each other. It takes a key of a persona's full
    # # name, and value of another persona's full name who is talking to the 
    # # original persona. 
    # # e.g., dict["Isabella Rodriguez"] = ["Maria Lopez"]
    # self.persona_convo_match = dict()
    # # <persona_convo> contains the actual content of the conversations. It
    # # takes as keys, a pair of persona names, and val of a string convo. 
    # # Note that the key pairs are *ordered alphabetically*. 
    # # e.g., dict[("Adam Abraham", "Zane Xu")] = "Adam: baba \n Zane:..."
    # self.persona_convo = dict()

    # Loading in all personas. 
    init_env_file = f"{sim_folder}/environment/{str(self.step)}.json"
    init_env = json.load(open(init_env_file))
    for persona_name in reverie_meta['persona_names']: 
      persona_folder = f"{sim_folder}/personas/{persona_name}"
      p_x = init_env[persona_name]["x"]
      p_y = init_env[persona_name]["y"]
      curr_persona = Persona(persona_name, persona_folder)

      self.personas[persona_name] = curr_persona
      self.personas_tile[persona_name] = (p_x, p_y)
      self.maze.tiles[p_y][p_x]["events"].add(curr_persona.scratch
                                              .get_curr_event_and_desc())

    # REVERIE SETTINGS PARAMETERS:  
    # <server_sleep> denotes the amount of time that our while loop rests each
    # cycle; this is to not kill our machine. 
    self.server_sleep = 0.01

    # SIGNALING THE FRONTEND SERVER: 
    # curr_sim_code.json contains the current simulation code, and
    # curr_step.json contains the current step of the simulation. These are 
    # used to communicate the code and step information to the frontend. 
    # Note that step file is removed as soon as the frontend opens up the 
    # simulation. 
    curr_sim_code = dict()
    curr_sim_code["sim_code"] = self.sim_code
    with open(f"{fs_temp_storage}/curr_sim_code.json", "w") as outfile: 
      outfile.write(json.dumps(curr_sim_code, indent=2))
    
    curr_step = dict()
    curr_step["step"] = self.step
    with open(f"{fs_temp_storage}/curr_step.json", "w") as outfile: 
      outfile.write(json.dumps(curr_step, indent=2))

    # Experiment logging for this run.
    scenario_id = globals().get("experiment_scenario_id", "datacenter_proposal_v1")
    self.experiment_logger = ExperimentLogger(
      sim_folder, self.sim_code, self.fork_sim_code,
      reverie_meta["persona_names"], scenario_id=scenario_id)
    self.experiment_logger.write_manifest()
    set_experiment_logger(self.experiment_logger)
    log.info(
      "Reverie ready: personas=%s step=%s time=%s maze=%s scenario=%s",
      reverie_meta["persona_names"], self.step, self.curr_time,
      reverie_meta["maze_name"], scenario_id)


  def save(self): 
    """
    Save all Reverie progress -- this includes Reverie's global state as well
    as all the personas.  

    INPUT
      None
    OUTPUT 
      None
      * Saves all relevant data to the designated memory directory
    """
    # <sim_folder> points to the current simulation folder.
    sim_folder = f"{fs_storage}/{self.sim_code}"
    log.info("Saving simulation %s at step=%s time=%s",
             self.sim_code, self.step, self.curr_time)

    # Save Reverie meta information.
    reverie_meta = dict() 
    reverie_meta["fork_sim_code"] = self.fork_sim_code
    reverie_meta["start_date"] = self.start_time.strftime("%B %d, %Y")
    reverie_meta["curr_time"] = self.curr_time.strftime("%B %d, %Y, %H:%M:%S")
    reverie_meta["sec_per_step"] = self.sec_per_step
    reverie_meta["maze_name"] = self.maze.maze_name
    reverie_meta["persona_names"] = list(self.personas.keys())
    reverie_meta["step"] = self.step
    reverie_meta_f = f"{sim_folder}/reverie/meta.json"
    with open(reverie_meta_f, "w") as outfile: 
      outfile.write(json.dumps(reverie_meta, indent=2))

    # Save the personas.
    for persona_name, persona in self.personas.items(): 
      save_folder = f"{sim_folder}/personas/{persona_name}/bootstrap_memory"
      persona.save(save_folder)

    # Snapshot agent state + outcomes marker for experiment tracking.
    if getattr(self, "experiment_logger", None):
      self.experiment_logger.log_snapshots(
        self.step, self.curr_time, self.personas)
      self.experiment_logger.log_outcomes(
        self.step, self.curr_time, self.personas, note="save")
    log.info("Save complete for %s", self.sim_code)


  def probe_opinions(self):
    """
    Reads where every agent stands on the datacenter, 0 (against) to
    STANCE_SCALE (in support), and logs it for the dashboard's stance graph.

    Measurement only: opinion_probe retrieves read-only and nothing is written
    to any agent's memory, so probing does not change the run it is watching.
    Agents with no clock yet have not stepped and have nothing to read.
    """
    model = run_env.chat_model(globals().get("chat_model"))
    caller = {k: usage.context[k] for k in ("persona", "source")}
    readings = []
    for name, persona in self.personas.items():
      if persona.scratch.curr_time is None:
        continue
      # Billed separately so probes don't show up as the cost of a step.
      usage.context.update(persona=name, source="opinion_probe",
                           step=self.step)
      reading = probe_opinion(persona, with_metadata=True)
      # The scale goes in every row: it moved from 10 to 100 once already, and
      # a bare score is unreadable without knowing which scale it was on.
      # <relevance> says how much the memories behind the rating had to do with
      # the datacenter at all, which a score alone cannot tell you, and
      # <withheld> separates the gaps the probe chose from the ones where the
      # model was asked and gave nothing usable. <quoted> counts the agent's
      # own spoken lines that went in beside the memories and the window they
      # came from, which is what would show a long run drawing its evidence
      # from one early week (see opinion_probe.quoted_span).
      readings += [{"name": name, "scale": STANCE_SCALE, **reading,
                    "model": model, "run_env": run_env.RUN_ENV}]
      shown = reading["relevance"]["shown"]
      log.info("  stance=%s %s rel=%s: %s", name,
               reading["withheld"] or reading["score"],
               "n/a" if shown is None else f"{shown:.2f}",
               (reading["rationale"] or "")[:120])
    usage.context.update(caller)
    if readings and getattr(self, "experiment_logger", None):
      self.experiment_logger.log_opinions(
        self.step, self.curr_time, readings)
    return readings


  def _load_whispers(self, clean_whispers):
    """
    Adds whispered memories via load_history_via_whisper. Personas that have
    not stepped yet have no clock, which add_thought needs for timestamps, so
    one is lent for the duration and then cleared again: a None clock is what
    makes Persona.move() run first-day planning.
    """
    unclocked = [p for p in self.personas.values()
                 if p.scratch.curr_time is None]
    for p in unclocked:
      p.scratch.curr_time = self.curr_time
    try:
      load_history_via_whisper(self.personas, clean_whispers)
    finally:
      for p in unclocked:
        p.scratch.curr_time = None


  def start_path_tester_server(self): 
    """
    Starts the path tester server. This is for generating the spatial memory
    that we need for bootstrapping a persona's state. 

    To use this, you need to open server and enter the path tester mode, and
    open the front-end side of the browser. 

    INPUT 
      None
    OUTPUT 
      None
      * Saves the spatial memory of the test agent to the path_tester_env.json
        of the temp storage. 
    """
    def print_tree(tree): 
      def _print_tree(tree, depth):
        dash = " >" * depth

        if type(tree) == type(list()): 
          if tree:
            print (dash, tree)
          return 

        for key, val in tree.items(): 
          if key: 
            print (dash, key)
          _print_tree(val, depth+1)
      
      _print_tree(tree, 0)

    # <curr_vision> is the vision radius of the test agent. Recommend 8 as 
    # our default. 
    curr_vision = 8
    # <s_mem> is our test spatial memory. 
    s_mem = dict()

    # The main while loop for the test agent. 
    while (True): 
      try: 
        curr_dict = {}
        tester_file = fs_temp_storage + "/path_tester_env.json"
        if check_if_file_exists(tester_file): 
          with open(tester_file) as json_file: 
            curr_dict = json.load(json_file)
            os.remove(tester_file)
          
          # Current camera location
          curr_sts = self.maze.sq_tile_size
          curr_camera = (int(math.ceil(curr_dict["x"]/curr_sts)), 
                         int(math.ceil(curr_dict["y"]/curr_sts))+1)
          curr_tile_det = self.maze.access_tile(curr_camera)

          # Initiating the s_mem
          world = curr_tile_det["world"]
          if curr_tile_det["world"] not in s_mem: 
            s_mem[world] = dict()

          # Iterating throughn the nearby tiles.
          nearby_tiles = self.maze.get_nearby_tiles(curr_camera, curr_vision)
          for i in nearby_tiles: 
            i_det = self.maze.access_tile(i)
            if (curr_tile_det["sector"] == i_det["sector"] 
                and curr_tile_det["arena"] == i_det["arena"]): 
              if i_det["sector"] != "": 
                if i_det["sector"] not in s_mem[world]: 
                  s_mem[world][i_det["sector"]] = dict()
              if i_det["arena"] != "": 
                if i_det["arena"] not in s_mem[world][i_det["sector"]]: 
                  s_mem[world][i_det["sector"]][i_det["arena"]] = list()
              if i_det["game_object"] != "": 
                if (i_det["game_object"] 
                    not in s_mem[world][i_det["sector"]][i_det["arena"]]):
                  s_mem[world][i_det["sector"]][i_det["arena"]] += [
                                                         i_det["game_object"]]

        # Incrementally outputting the s_mem and saving the json file. 
        print ("= " * 15)
        out_file = fs_temp_storage + "/path_tester_out.json"
        with open(out_file, "w") as outfile: 
          outfile.write(json.dumps(s_mem, indent=2))
        print_tree(s_mem)

      except:
        pass

      time.sleep(self.server_sleep * 10)


  def start_server(self, int_counter): 
    """
    The main backend server of Reverie. 
    This function retrieves the environment file from the frontend to 
    understand the state of the world, calls on each personas to make 
    decisions based on the world state, and saves their moves at certain step
    intervals. 
    INPUT
      int_counter: Integer value for the number of steps left for us to take
                   in this iteration. 
    OUTPUT 
      None
    """
    # <sim_folder> points to the current simulation folder.
    sim_folder = f"{fs_storage}/{self.sim_code}"
    log.info("Starting server loop for %s steps (from step=%s)",
             int_counter, self.step)
    # Set by a "stop" command (dashboard or terminal) to end the run early.
    self._stop_requested = False

    # When a persona arrives at a game object, we give a unique event
    # to that object. 
    # e.g., ('double studio[...]:bed', 'is', 'unmade', 'unmade')
    # Later on, before this cycle ends, we need to return that to its 
    # initial state, like this: 
    # e.g., ('double studio[...]:bed', None, None, None)
    # So we need to keep track of which event we added. 
    # <game_obj_cleanup> is used for that. 
    game_obj_cleanup = dict()

    # The main while loop of Reverie. 
    while (True): 
      # Done with this iteration if <int_counter> reaches 0.
      if int_counter == 0 or self._stop_requested:
        if self._stop_requested:
          log.info("Run stopped early with %s steps left", int_counter)
        break

      # <curr_env_file> file is the file that our frontend outputs. When the
      # frontend has done its job and moved the personas, then it will put a 
      # new environment file that matches our step count. That's when we run 
      # the content of this for loop. Otherwise, we just wait. 
      curr_env_file = f"{sim_folder}/environment/{self.step}.json"
      # Reset every pass: a failed read must not reuse the last step's
      # positions (or hit an unset name on the first pass).
      env_retrieved = False
      if check_if_file_exists(curr_env_file):
        # If we have an environment file, it means we have a new perception
        # input to our personas. So we first retrieve it.
        try: 
          # Try and save block for robustness of the while loop.
          with open(curr_env_file) as json_file:
            new_env = json.load(json_file)
            env_retrieved = True
        except: 
          pass
      
        if env_retrieved: 
          if getattr(self, "experiment_logger", None):
            self.experiment_logger.set_step(self.step)
          # This is where we go through <game_obj_cleanup> to clean up all 
          # object actions that were used in this cylce. 
          for key, val in game_obj_cleanup.items(): 
            # We turn all object actions to their blank form (with None). 
            self.maze.turn_event_from_tile_idle(key, val)
          # Then we initialize game_obj_cleanup for this cycle. 
          game_obj_cleanup = dict()

          # We first move our personas in the backend environment to match 
          # the frontend environment. 
          for persona_name, persona in self.personas.items(): 
            # <curr_tile> is the tile that the persona was at previously. 
            curr_tile = self.personas_tile[persona_name]
            # <new_tile> is the tile that the persona will move to right now,
            # during this cycle. 
            new_tile = (new_env[persona_name]["x"], 
                        new_env[persona_name]["y"])

            # We actually move the persona on the backend tile map here. 
            self.personas_tile[persona_name] = new_tile
            self.maze.remove_subject_events_from_tile(persona.name, curr_tile)
            self.maze.add_event_from_tile(persona.scratch
                                         .get_curr_event_and_desc(), new_tile)

            # Now, the persona will travel to get to their destination. *Once*
            # the persona gets there, we activate the object action.
            if not persona.scratch.planned_path: 
              # We add that new object action event to the backend tile map. 
              # At its creation, it is stored in the persona's backend. 
              game_obj_cleanup[persona.scratch
                               .get_curr_obj_event_and_desc()] = new_tile
              self.maze.add_event_from_tile(persona.scratch
                                     .get_curr_obj_event_and_desc(), new_tile)
              # We also need to remove the temporary blank action for the 
              # object that is currently taking the action. 
              blank = (persona.scratch.get_curr_obj_event_and_desc()[0], 
                       None, None, None)
              self.maze.remove_event_from_tile(blank, new_tile)

          # Then we need to actually have each of the personas perceive and
          # move. The movement for each of the personas comes in the form of
          # x y coordinates where the persona will move towards. e.g., (50, 34)
          # This is where the core brains of the personas are invoked. 
          movements = {"persona": dict(), 
                       "meta": dict()}
          step_t0 = time.time()
          log.info("Step %s begin | game_time=%s | agents=%s",
                   self.step, self.curr_time, list(self.personas.keys()))
          for persona_name, persona in self.personas.items(): 
            # <next_tile> is a x,y coordinate. e.g., (58, 9)
            # <pronunciatio> is an emoji. e.g., "\ud83d\udca4"
            # <description> is a string description of the movement. e.g., 
            #   writing her next novel (editing her novel) 
            #   @ double studio:double studio:common room:sofa
            agent_t0 = time.time()
            usage.context.update(persona=persona_name, source="step",
                                 step=self.step)
            next_tile, pronunciatio, description = persona.move(
              self.maze, self.personas, self.personas_tile[persona_name], 
              self.curr_time)
            agent_dt = time.time() - agent_t0
            usage.context["persona"] = None
            movements["persona"][persona_name] = {}
            movements["persona"][persona_name]["movement"] = next_tile
            movements["persona"][persona_name]["pronunciatio"] = pronunciatio
            movements["persona"][persona_name]["description"] = description
            movements["persona"][persona_name]["chat"] = (persona
                                                          .scratch.chat)
            chat_note = ""
            if persona.scratch.chat:
              chat_note = f" | chatting_with={persona.scratch.chatting_with}"
            log.info(
              "  agent=%s (%.2fs) tile=%s act=%s%s",
              persona_name, agent_dt, next_tile,
              (description or "")[:120], chat_note)

          # Include the meta information about the current stage in the 
          # movements dictionary. 
          movements["meta"]["curr_time"] = (self.curr_time 
                                             .strftime("%B %d, %Y, %H:%M:%S"))

          # We then write the personas' movements to a file that will be sent 
          # to the frontend server. 
          # Example json output: 
          # {"persona": {"Maria Lopez": {"movement": [58, 9]}},
          #  "persona": {"Klaus Mueller": {"movement": [38, 12]}}, 
          #  "meta": {curr_time: <datetime>}}
          curr_move_file = f"{sim_folder}/movement/{self.step}.json"
          _write_json_atomic(curr_move_file, movements)

          # Write the next step's positions ourselves instead of waiting for
          # the browser map to report them, so runs keep going in a hidden
          # tab or with no map open. The map only ever set each agent onto
          # its movement tile, so these are the positions it would report;
          # it now just displays them (process_environment won't overwrite).
          _write_json_atomic(
            f"{sim_folder}/environment/{self.step + 1}.json",
            {name: {"maze": self.maze.maze_name, "x": m["movement"][0], 
                    "y": m["movement"][1]}
             for name, m in movements["persona"].items()})

          # After this cycle, the world takes one step forward, and the 
          # current time moves by <sec_per_step> amount. 
          self.step += 1
          self.curr_time += datetime.timedelta(seconds=self.sec_per_step)

          snap_n = globals().get("snapshot_every_n_steps", 50)
          if (getattr(self, "experiment_logger", None)
              and snap_n and self.step % snap_n == 0):
            self.experiment_logger.log_snapshots(
              self.step, self.curr_time, self.personas)

          log.info("Step %s done in %.2fs -> next_step=%s",
                   self.step - 1, time.time() - step_t0, self.step)
          int_counter -= 1

          # Settings come from the dashboard and apply mid-run.
          settings = load_settings()
          opinion_every = settings.get("opinion_steps") or 0
          if opinion_every and self.step % opinion_every == 0:
            self.probe_opinions()
          every = settings.get("autosave_steps") or 0
          if every and self.step % every == 0: 
            log.info("Auto-saving at step %s (every %s steps)", self.step, every)
            self.save()
            self.last_autosave = self.step
          cap = settings.get("budget_usd")
          if cap is not None and usage.run_cost >= cap: 
            log.warning("Spending cap $%.2f reached ($%.4f spent); stopping "
                        "and saving at step %s", cap, usage.run_cost, self.step)
            self.budget_hit = True
            if getattr(self, "last_autosave", None) != self.step:
              self.save()
              self.last_autosave = self.step
            write_state(self, "running", 0)
            break
          write_state(self, "running", int_counter, force=False)

      # Sleep so we don't burn our machines. 
      time.sleep(self.server_sleep)


  def open_server(self, initial_commands=()): 
    """
    Open up an interactive terminal prompt that lets you run the simulation 
    step by step and probe agent state. 

    INPUT 
      None
    OUTPUT
      None
    """
    print ("Note: The agents in this simulation package are computational")
    print ("constructs powered by generative agents architecture and LLM. We")
    print ("clarify that these agents lack human-like agency, consciousness,")
    print ("and independent decision-making.\n---")

    # <sim_folder> points to the current simulation folder.
    sim_folder = f"{fs_storage}/{self.sim_code}"

    # Commands arrive from the terminal and from the web dashboard.
    self._stop_requested = False
    self._interviews = dict()
    feed = CommandFeed(on_stop=self.request_stop, initial=initial_commands)
    write_state(self, "idle")

    while True:
      print ("Enter option: ", end="", flush=True)
      cmd_id, sim_command = feed.get()
      sim_command = sim_command.strip()
      ret_str = ""
      finished = False
      log.info("CLI command: %r", sim_command)
      # Calls made by this command (whispers, interviews) are billed to it.
      usage.context.update(persona=None, step=self.step,
                           source=" ".join(sim_command.split(";;")[0].split()[:3]))

      try:
        if sim_command.lower() in ["f", "fin", "finish", "save and finish"]:
          # Finishes the simulation environment and saves the progress.
          # Example: fin
          log.info("Finishing and saving simulation")
          self.save()
          ret_str += f"Saved at step {self.step}. The simulation server has stopped."
          finished = True

        elif sim_command.lower() == "start path tester mode": 
          # Starts the path tester and removes the currently forked sim files.
          # Note that once you start this mode, you need to exit out of the
          # session and restart in case you want to run something else. 
          log.warning("Entering path tester mode; deleting sim folder %s", sim_folder)
          shutil.rmtree(sim_folder) 
          self.start_path_tester_server()

        elif sim_command.lower() == "exit": 
          # Finishes the simulation environment but does not save the progress
          # and erases all saved data from current simulation. 
          # Example: exit 
          log.warning("Exiting without save; deleting sim folder %s", sim_folder)
          shutil.rmtree(sim_folder)
          ret_str += f"Deleted {self.sim_code} without saving."
          finished = True

        elif sim_command.lower() == "save":
          # Saves the current simulation progress.
          # Example: save
          self.save()
          ret_str += f"Saved at step {self.step}."

        elif sim_command[:3].lower() == "run":
          # Runs the number of steps specified in the prompt.
          # Example: run 1000
          int_count = int(sim_command.split()[-1])
          cap = load_settings().get("budget_usd")
          if cap is not None and usage.run_cost >= cap: 
            ret_str += (f"Not started: this run has spent ${usage.run_cost:.4f}, "
                        f"which is over the ${cap:.2f} spending cap. Raise the "
                        f"cap to keep going.")
          else: 
            log.info("Run requested for %s steps", int_count)
            self.budget_hit = False
            write_state(self, "running", int_count)
            self.start_server(int_count)
            ret_str += (f"Now at step {self.step}, "
                        f"{self.curr_time.strftime('%B %d, %H:%M')}.")
            if self.budget_hit: 
              ret_str += (f" Stopped early: the ${load_settings().get('budget_usd') or 0:.2f} spending cap was "
                          f"reached (${usage.run_cost:.4f} spent). Saved.")

        elif ("print persona schedule" 
              in sim_command[:22].lower()): 
          # Print the decomposed schedule of the persona specified in the 
          # prompt.
          # Example: print persona schedule Isabella Rodriguez
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                      .scratch.get_str_daily_schedule_summary())

        elif ("print all persona schedule" 
              in sim_command[:26].lower()): 
          # Print the decomposed schedule of all personas in the world. 
          # Example: print all persona schedule
          for persona_name, persona in self.personas.items(): 
            ret_str += f"{persona_name}\n"
            ret_str += f"{persona.scratch.get_str_daily_schedule_summary()}\n"
            ret_str += f"---\n"

        elif ("print hourly org persona schedule" 
              in sim_command.lower()): 
          # Print the hourly schedule of the persona specified in the prompt.
          # This one shows the original, non-decomposed version of the 
          # schedule.
          # Ex: print persona schedule Isabella Rodriguez
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                      .scratch.get_str_daily_schedule_hourly_org_summary())

        elif ("print persona current tile" 
              in sim_command[:26].lower()): 
          # Print the x y tile coordinate of the persona specified in the 
          # prompt. 
          # Ex: print persona current tile Isabella Rodriguez
          ret_str += str(self.personas[" ".join(sim_command.split()[-2:])]
                      .scratch.curr_tile)

        elif ("print persona chatting with buffer" 
              in sim_command.lower()): 
          # Print the chatting with buffer of the persona specified in the 
          # prompt.
          # Ex: print persona chatting with buffer Isabella Rodriguez
          curr_persona = self.personas[" ".join(sim_command.split()[-2:])]
          for p_n, count in curr_persona.scratch.chatting_with_buffer.items(): 
            ret_str += f"{p_n}: {count}"

        elif ("print persona associative memory (event)" 
              in sim_command.lower()):
          # Print the associative memory (event) of the persona specified in
          # the prompt
          # Ex: print persona associative memory (event) Isabella Rodriguez
          ret_str += f'{self.personas[" ".join(sim_command.split()[-2:])]}\n'
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                                       .a_mem.get_str_seq_events())

        elif ("print persona associative memory (thought)" 
              in sim_command.lower()): 
          # Print the associative memory (thought) of the persona specified in
          # the prompt
          # Ex: print persona associative memory (thought) Isabella Rodriguez
          ret_str += f'{self.personas[" ".join(sim_command.split()[-2:])]}\n'
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                                       .a_mem.get_str_seq_thoughts())

        elif ("print persona associative memory (chat)" 
              in sim_command.lower()): 
          # Print the associative memory (chat) of the persona specified in
          # the prompt
          # Ex: print persona associative memory (chat) Isabella Rodriguez
          ret_str += f'{self.personas[" ".join(sim_command.split()[-2:])]}\n'
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                                       .a_mem.get_str_seq_chats())

        elif ("print persona spatial memory" 
              in sim_command.lower()): 
          # Print the spatial memory of the persona specified in the prompt
          # Ex: print persona spatial memory Isabella Rodriguez
          self.personas[" ".join(sim_command.split()[-2:])].s_mem.print_tree()

        elif ("print current time" 
              in sim_command[:18].lower()): 
          # Print the current time of the world. 
          # Ex: print current time
          ret_str += f'{self.curr_time.strftime("%B %d, %Y, %H:%M:%S")}\n'
          ret_str += f'steps: {self.step}'

        elif ("print tile event" 
              in sim_command[:16].lower()): 
          # Print the tile events in the tile specified in the prompt 
          # Ex: print tile event 50, 30
          cooordinate = [int(i.strip()) for i in sim_command[16:].split(",")]
          for i in self.maze.access_tile(cooordinate)["events"]: 
            ret_str += f"{i}\n"

        elif ("print tile details" 
              in sim_command.lower()): 
          # Print the tile details of the tile specified in the prompt 
          # Ex: print tile event 50, 30
          cooordinate = [int(i.strip()) for i in sim_command[18:].split(",")]
          for key, val in self.maze.access_tile(cooordinate).items(): 
            ret_str += f"{key}: {val}\n"

        elif ("call -- analysis" 
              in sim_command.lower()): 
          # Starts a stateless chat session with the agent. It does not save 
          # anything to the agent's memory. 
          # Ex: call -- analysis Isabella Rodriguez
          # The interactive session read its own input(), which now competes
          # with the command queue, so interviews go one question at a time.
          ret_str += ("Interviews run one question at a time: "
                      "call -- interview <Agent Name> ;; <question>\n")

        elif ("call -- interview" in sim_command.lower()):
          # Stateless interview, like "analysis": nothing is added to the
          # agent's memory, and the retrieval behind the answer is read-only
          # (touch=False), so interviewing an agent does not change what it
          # retrieves next. Earlier questions stay as context until end_convo.
          # Ex: call -- interview Elena Chen ;; What do you think of the datacenter?
          # Ex: call -- interview Elena Chen ;; end_convo
          name, line = [x.strip() for x in
                        sim_command[len("call -- interview"):].split(";;", 1)]
          persona = self.personas[name]
          usage.context["persona"] = name
          convo = self._interviews.setdefault(name, [])
          if line == "end_convo":
            self._interviews.pop(name, None)
            ret_str += f"Interview with {name} closed."
          elif int(run_gpt_generate_safety_score(persona, line)[0] or 0) >= 8:
            ret_str += (f"{name} is a computational agent, and as such, it may "
                        "be inappropriate to attribute human agency to the "
                        "agent in your communication.")
          else:
            retrieved = new_retrieve(persona, [line], 50, touch=False)[line]
            summarized_idea = generate_summarize_ideas(persona, retrieved, line)
            convo += [["Interviewer", line]]
            answer = generate_next_line(persona, "Interviewer", convo,
                                        summarized_idea)
            convo += [[name, answer]]
            ret_str += answer

        elif ("call -- load history" 
              in sim_command.lower()): 
          curr_file = maze_assets_loc + "/" + sim_command[len("call -- load history"):].strip() 
          # call -- load history the_ville/agent_history_init_n3.csv

          rows = read_file_to_list(curr_file, header=True, strip_trail=True)[1]
          clean_whispers = []
          for row in rows: 
            agent_name = row[0].strip() 
            whispers = row[1].split(";")
            whispers = [whisper.strip() for whisper in whispers]
            for whisper in whispers: 
              clean_whispers += [[agent_name, whisper]]

          self._load_whispers(clean_whispers)
          log.info("Loaded history: %s whispers from %s",
                   len(clean_whispers), curr_file)
          if getattr(self, "experiment_logger", None):
            for agent_name, whisper in clean_whispers:
              self.experiment_logger.log_event(
                self.step, self.curr_time, "history_whisper",
                agent=agent_name, text=whisper,
                extra={"source_file": curr_file})

        elif ("call -- probe now" in sim_command.lower()):
          # Reads every agent's position on the datacenter right now instead
          # of waiting for the next scheduled read. Useful straight after a
          # whisper, to catch the before and after.
          # Ex: call -- probe now
          readings = self.probe_opinions()
          for reading in readings:
            ret_str += (f"{reading['name']}: "
                        f"{reading['score'] if reading['score'] is not None else '-'}"
                        f" {reading['rationale']}\n")
          if not readings:
            ret_str += "No agents have stepped yet, so there is nothing to read.\n"

        elif ("call -- whisper" in sim_command.lower()):
          # Mid-run event injection.
          # Ex: call -- whisper Maya Okonkwo ;; The council posted the proposal summary.
          # Ex: call -- whisper all ;; Utility company issued a statement on grid capacity.
          payload = sim_command[len("call -- whisper"):].strip()
          if ";;" not in payload:
            ret_str += "Usage: call -- whisper <Agent Name|all> ;; <text>\n"
          else:
            target_part, whisper_text = payload.split(";;", 1)
            target_part = target_part.strip()
            whisper_text = whisper_text.strip()
            if target_part.lower() == "all":
              targets = list(self.personas.keys())
            else:
              targets = [target_part]
            clean_whispers = [[name, whisper_text] for name in targets]
            self._load_whispers(clean_whispers)
            log.info("Mid-run whisper to %s agent(s): %s",
                     len(clean_whispers), whisper_text[:160])
            if getattr(self, "experiment_logger", None):
              for agent_name, whisper in clean_whispers:
                self.experiment_logger.log_event(
                  self.step, self.curr_time, "midrun_whisper",
                  agent=agent_name, text=whisper)
            ret_str += f"Whispered to {len(clean_whispers)} agent(s).\n"

        print (ret_str)
        record_result(cmd_id, sim_command, True, ret_str)

      except:
        traceback.print_exc()
        log.exception("CLI command failed: %r", sim_command)
        print ("Error.")
        record_result(cmd_id, sim_command, False, traceback.format_exc())

      if finished:
        write_state(self, "finished")
        break
      write_state(self, "idle")


  def request_stop(self):
    self._stop_requested = True


if __name__ == '__main__':
  # rs = ReverieServer("base_the_ville_isabella_maria_klaus",
  #                    "July1_the_ville_isabella_maria_klaus-step-3-1")
  # rs = ReverieServer("July1_the_ville_isabella_maria_klaus-step-3-20",
  #                    "July1_the_ville_isabella_maria_klaus-step-3-21")
  # rs.open_server()

  setup_logging()
  # The dashboard launches:
  #   reverie.py <fork> <new sim> [--history <csv>] [--run <steps>]
  # History loads first, then the run starts. With no arguments, ask in the
  # terminal as before.
  args = sys.argv[1:]
  initial_commands = []
  if "--history" in args:
    i = args.index("--history")
    initial_commands += [f"call -- load history {args[i + 1]}"]
    args = args[:i] + args[i + 2:]
  if "--run" in args:
    i = args.index("--run")
    initial_commands += [f"run {int(args[i + 1])}"]
    args = args[:i] + args[i + 2:]
  if len(args) == 2:
    origin, target = args
  else:
    origin = input("Enter the name of the forked simulation: ").strip()
    target = input("Enter the name of the new simulation: ").strip()
  target = run_env.run_name(target)
  log.info("User selected fork=%s target=%s (run_env=%s)", origin, target,
           run_env.RUN_ENV)

  rs = ReverieServer(origin, target)
  rs.open_server(initial_commands)




















































