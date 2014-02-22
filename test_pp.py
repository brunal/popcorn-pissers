import unittest
from datetime import datetime

from praw import objects, Reddit as R

from pp import PopcornPisser, OrderedComment

try:
    # python 3
    from unittest.mock import MagicMock
except ImportError:
    # python 2
    from mock import MagicMock


class TestOrderedComment(unittest.TestCase):
    class Dummy(object):
        pass

    def test_order(self):
        c1 = OrderedComment(self.Dummy())
        c1.created_utc = datetime(2010, 1, 1)
        c2 = OrderedComment(self.Dummy())
        c2.created_utc = datetime(2012, 1, 1)

        self.assertTrue(c2 > c1)


class TestPopcornPisser(unittest.TestCase):
    def test_get_submissions(self):
        Subreddit = MagicMock(autospec=objects.Subreddit)
        subreddit = Subreddit()

        s1 = MagicMock(name='s1')
        s1.name = 's1'
        s2 = MagicMock(name='s2')
        s2.name = 's2'
        subreddit.get_hot.return_value = [s1, s2]

        pp = PopcornPisser(subreddit)
        hot_and_new = pp.get_submissions_to_watch()

        subreddit.get_hot.assert_called_once_with(limit=10)

        self.assertEqual(pp.submissions_seen, {'s1', 's2'})
        self.assertEqual(hot_and_new, [s1, s2])

        subreddit.get_hot.return_value = [s1]
        hot_and_new = pp.get_submissions_to_watch()

        self.assertEqual(pp.submissions_seen, {'s1', 's2'})
        self.assertEqual(hot_and_new, [])


class TestSubmissionWatcher(unittest.TestCase):
    pass
