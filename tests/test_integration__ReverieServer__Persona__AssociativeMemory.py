import os
import sys

this_dir = os.path.abspath(os.path.dirname(__file__))
reverie_loc = os.path.abspath(f"{this_dir}/../reverie/backend_server")
sys.path.insert(0, reverie_loc)


import logging
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

import reverie
from reverie import ReverieServer
from persona.persona import Persona

import pytest

import datetime as dt
import shutil



# To the user: set with your OpenAI API key.
reverie.openai_api_key=""
reverie.key_owner=""


class ReverieTestServer(ReverieServer):
  '''
  Version of ReverieServer for test fixtures.
  '''
  def __init__(self, fork_sim_code, sim_code, predelete=False):
    '''
    Overrides ReverieServer.__init__() to optionally predelete sim directory

    Predelete is for test purposes.
    '''
    sim_path=f'{reverie.fs_storage}/{sim_code}'
    if predelete and os.path.exists(sim_path):
      shutil.rmtree(sim_path)
    super().__init__(fork_sim_code=fork_sim_code, sim_code=sim_code)


@pytest.fixture
def rs():
  fork_sim_code = 'July1_the_ville_isabella_maria_klaus-step-3-20'
  sim_code = 'test-simulation'
  return ReverieTestServer(
    fork_sim_code=fork_sim_code,
    sim_code=sim_code,
    predelete=True,
  )


def test__reverie__Persona__scratch__get_str_iss(rs):
  '''Verify Scratch.get_str_iss() doesn't raise exceptions.'''
  isabella = rs.personas['Isabella Rodriguez']
  # Retrieval of identity stable set
  iss = isabella.scratch.get_str_iss()
  log.debug(
    f'''
*** Persona identity:
{iss}
''')


def test__reverie__Persona__scratch__get_str_daily_schedule_summary(rs):
  '''Verify Scratch.get_str_daily_schedule_summary() doesn't raise exceptions.'''
  isabella = rs.personas['Isabella Rodriguez']
  # Retrieval of daily schedule
  daily_schedule = isabella.scratch.get_str_daily_schedule_summary()
  log.debug(
    f'''

*** Persona daily schedule:
{daily_schedule}
''')


def test__reverie__Persona__scratch__get_str_hourly_schedule_summary(rs):
  '''Verify Scratch.get_str_daily_schedule_hourly_org_summary() doesn't raise exceptions.'''
  isabella = rs.personas['Isabella Rodriguez']
  # Retrieval of hourly schedule
  hourly_schedule = isabella.scratch.get_str_daily_schedule_hourly_org_summary()
  log.debug(
    f'''
*** Persona hourly schedule:
{hourly_schedule}
''')


def test__reverie__Persona__scratch__get_str_seq_events(rs):
  '''Verify AssociativeMemory.get_str_seq_events() doesn't raise exceptions.'''
  isabella = rs.personas['Isabella Rodriguez']
  # Retrieval of associative memory (event)
  event_memories = isabella.a_mem.get_str_seq_events()
  log.debug(
    f'''
*** Persona event memories:
{event_memories}
''')


def test__reverie__Persona__scratch__get_str_seq_thoughts(rs):
  '''Verify AssociativeMemory.get_str_seq_thoughts() doesn't raise exceptions.'''
  isabella = rs.personas['Isabella Rodriguez']
  # Retrieval of associative memory (thought)
  thought_memories = isabella.a_mem.get_str_seq_thoughts()
  log.debug(
    f'''
*** Persona thought memories:
{thought_memories}
''')


def test__reverie__Persona__scratch__get_str_seq_chats(rs):
  '''Verify AssociativeMemory.get_str_seq_chats() doesn't raise exceptions.'''
  isabella = rs.personas['Isabella Rodriguez']
  # Rewrite of method body that correctly accesses 
  chat_memories = isabella.a_mem.get_str_seq_chats()
  log.debug(
    f'''
*** Persona chat memories:
{chat_memories}
''')