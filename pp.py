#!/usr/bin/env python
"""
This module defines a reddit bot that will look at SRD submissions, follow the
link and look for "popcorn pissers".
"""
from configparser import ConfigParser
from threading import Thread
from time import sleep
import logging

import praw

logging.getLogger().setLevel(logging.INFO)

config = ConfigParser()
config.read('settings.txt')

r = praw.Reddit("popcorn-pissers")
r.login(config.get('auth', 'username'),
        config.get('auth', 'password'))
logging.info("Bot logged in")

subreddit = config.get('subreddit', 'subreddit')
s = r.get_subreddit(subreddit)


class PopcornPisser(Thread):
    """Indefinitely look for new submissions and watch them"""
    def __init__(self):
        super(PopcornPisser, self).__init__()
        self.submissions_seen = set()

    def get_submissions_to_watch(self):
        """Get hot submissions that haven't been treated"""
        hot = set(s.get_hot(limit=10))
        hot_and_new = filter(lambda h: h.name not in self.submissions_seen, hot)
        self.submissions_seen |= {h.name for h in hot_and_new}
        return hot_and_new

    def run(self):
        logging.info("Bot started")

        while True:
            submissions = self.get_submissions_to_watch()
            logging.info("%s got %s new submissions to watch",
                         self.__class__.__name__, len(submissions))
            for submission in submissions:
                sw = SubmissionWatcher(submission)
                sw.start()
            sleep(30 * 60)


class SubmissionWatcher(Thread):
    """Each instance is responsible of watching a single reddit thread"""
    def __init__(self, thread):
        super(SubmissionWatcher, self).__init__()
        self.thread = thread
        self.popcorn_pissers = []
        self.commenters_seen = set()

    def is_member_of_subreddit(self, user, subreddit):
        """Return whether `user` is active in `subreddit`

        That check is more tricky than it might seem: if `user` previously
        pissed in the popcorn in `subreddit` he may be seen as a member.
        """
        return False

    def get_commenters(self):
        return []

    def run(self):
        logging.info("Watching submission %s", self.thread)
        while True:
            for user, comments in self.get_commenters():
                if not self.is_member_of_subreddit(user, self.target_subreddit):
                    self.popcorn_pissers.append((user, comments))

            logging.info("Found %s popcorn pissers in thread %s",
                         len(self.popcorn_pissers), self.thread)
            self.generate_report()

    def generate_report(self):
        pass


if __name__ == '__main__':
    pp = PopcornPisser()
    pp.start()
