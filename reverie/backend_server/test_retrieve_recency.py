import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from persona.cognitive_modules import retrieve


class TestMemoryRecency(unittest.TestCase):
  def setUp(self):
    now = datetime(2023, 2, 14, 10)
    scratch = SimpleNamespace(curr_time=now, recency_decay=0.995,
                              recency_w=1, relevance_w=1, importance_w=1)
    self.nodes = [
      SimpleNamespace(node_id=name, last_accessed=now - timedelta(hours=age),
                      embedding_key=name, poignancy=5)
      for name, age in [('old', 24), ('new', 0), ('recent', 0.5), ('tie', 0.5)]
    ]
    memory = SimpleNamespace(seq_event=[], seq_thought=self.nodes,
                             embeddings={n.embedding_key: [1, 0] for n in self.nodes},
                             id_to_node={n.node_id: n for n in self.nodes})
    self.persona = SimpleNamespace(scratch=scratch, a_mem=memory)

  def test_decay_by_elapsed_game_hours(self):
    scores = retrieve.extract_recency(self.persona, self.nodes)
    self.assertEqual(scores, {'old': 0.995 ** 24, 'new': 1.0,
                              'recent': 0.995 ** 0.5, 'tie': 0.995 ** 0.5})

  @patch.object(retrieve, 'get_embedding', return_value=[1, 0])
  def test_retrieve_most_recent_when_other_scores_tie(self, _embedding):
    result = retrieve.new_retrieve(self.persona, ['query'], n_count=1)
    self.assertEqual(result['query'][0].node_id, 'new')
