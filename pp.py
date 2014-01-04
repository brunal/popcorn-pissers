#!/usr/bin/env python
"""
This module defines a reddit bot that will look at SRD submissions, follow the
link and look for "popcorn pissers".
"""
from configparser import ConfigParser
from io import StringIO
from threading import Thread
from time import sleep
from collections import deque
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
    """Each instance is responsible for watching a single reddit thread"""
    def __init__(self, submission):
        super(SubmissionWatcher, self).__init__()

        self.submission = submission
        self.target = r.get_submission(submission.url)

        self.popcorn_pissers = []
        self.commenters_seen = set()

        self.comment_posted = None

    def is_member_of_subreddit(self, user, subreddit):
        """Return whether `user` is active in `subreddit`

        That check is more tricky than it might seem: if `user` previously
        pissed in the popcorn in `subreddit` he may be seen as a member.
        """
        overview = user.get_overview(limit=100)
        return any(o.subreddit == subreddit for o in overview)

    def get_commenters(self):
        """Get all commenters and their comments"""
        commenters = dict()  # author to comments dict
        comments = deque(self.target.comments)  # comments left to treat
        while len(comments):
            c = comments.popleft()
            comments.extend(c.replies)

            if c.author in self.commenters_seen:
                continue

            if c.author not in commenters:
                commenters[c.author] = []
            commenters[c.author].append(c)

        self.commenters_seen |= commenters.keys()
        return commenters

    def we_can_handle_it(self):
        """Return whether we're able to watch the submission"""
        return not (self.submission.is_self or
                    self.submission.domain.endswith('reddit.com'))

    def run(self):
        logging.info("Watching submission %s", self.submission.short_link)
        if not self.we_can_handle_it():
            logging.info("Stopping watcher for submission %s: unable to handle it",
                         self.submission.short_link)
            return

        while True:
            for user, comments in self.get_commenters():
                if not self.is_member_of_subreddit(user, self.target.subreddit):
                    self.popcorn_pissers.append((user, comments))

            logging.info("Found %s popcorn pissers in thread %s",
                         len(self.popcorn_pissers), self.submission.short_link)
            if len(self.popcorn_pissers) > 0:
                self.generate_report()

    def generate_report(self):
        report = self.generate_report_text()
        if self.comment_posted is None:
            self.comment_posted = self.submission.add_comment(report)
        else:
            self.comment_posted.edit(report)

    def generate_report_text(self):
        s = StringIO()
        s.write("I found the following popcorn pissers in the thread:\n\n")
        for user, comments in self.popcorn_pissers:
            s.write("* /u/%s: " % user.name)
            for i, c in enumerate(comments):
                s.write("[%s](%s) " % (i + 1, c.permalink))
            s.write("\n")
        return s.getvalue()

if __name__ == '__main__':
    pp = PopcornPisser()
    pp.start()
