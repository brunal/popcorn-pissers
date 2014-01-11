#!/usr/bin/env python
"""
This module defines a reddit bot that will look at SRD submissions, follow the
link and look for "popcorn pissers".
"""
try:
    # python 3
    from configparser import ConfigParser
    from io import StringIO
except ImportError:
    # python 2
    from ConfigParser import ConfigParser
    from cStringIO import StringIO

from threading import Thread
from time import sleep
import heapq
from functools import total_ordering
import logging as log

import praw

logging = log.getLogger('bru.pp')
logging.setLevel(log.DEBUG)

stderr = log.StreamHandler()
stderr.setLevel(log.INFO)
logging.addHandler(stderr)

to_file = log.FileHandler('log.txt')
to_file.setLevel(log.DEBUG)
logging.addHandler(to_file)

logging.debug("Loggers configured")

logging.debug("Patching praw.objects.Comment for comp on created_utc")


@total_ordering
class MyComment(praw.objects.Comment):
    def __gt__(self, other):
        return self.created_utc > other.created_utc
praw.objects.Comment = MyComment

config = ConfigParser()
config.read('settings.txt')

r = praw.Reddit("popcorn-pissers by /u/Laugarhraun")
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
        hot = s.get_hot(limit=10)
        hot_and_new = [h for h in hot if h.name not in self.submissions_seen]
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
        self.target = None  # load it later, in its own thread
        self.short_name = submission.short_link

        self.popcorn_pissers = []
        self.commenters_seen = set()

        self.comment_posted = None

    def is_member_of_subreddit(self, user, subreddit):
        """Return whether `user` is active in `subreddit`

        That check is more tricky than it might seem: if `user` previously
        pissed in the popcorn in `subreddit` he may be seen as a member.
        """
        overview = user.get_overview(limit=100)
        for o in overview:
            if o.subreddit == subreddit:
                try:
                    # must not be a comment from the watched thread
                    if o.submission != self.target:
                        logging.debug("%s cleared by comment %s", user.name, o.permalink)
                        return True
                except AttributeError:
                    # `user` submitted something in that subreddit
                    logging.debug("%s cleared by item %s", user.name, o)
                    return True

    def get_recent_commenters(self):
        """Get all commenters after submission creation and their comments

        We need to handle the comments from oldest to youngest, so that if a
        redditor posted before and after the thread submission he's always
        cleared. We need quick oldest retrieval and insertion of comment so
        we'll use a heap."""
        logging.debug("Looking for commenters in %s target", self.short_name)

        commenters = dict()  # author name to author-comments dict
        comments = heapq.heapify(self.target.comments)
        while len(comments):
            logging.debug("%s: %s users seen, %s messages left to do",
                          self.short_name, len(commenters), len(comments))

            c = heapq.heappop(comments)
            try:
                for c_ in c.replies:
                    heapq.heappush(comments, c_)
            except AttributeError:
                # we have a MoreComments object
                try:
                    for c_ in c.comments():
                        heapq.heappush(comments, c_)
                except:
                    logging.exception("Unable to manage MoreComments %s", c.fullname)
                continue

            if c.author is None:
                continue

            author_name = c.author.name
            if author_name in self.commenters_seen:
                continue

            if c.created_utc < self.submission.created_utc:
                # comment older than the submission, whitelist the poster
                self.commenters_seen.add(author_name)
                continue

            if author_name not in commenters:
                commenters[author_name] = (c.author, [])
                yield commenters[author_name]
            commenters[author_name][1].append(c.permalink)

        self.commenters_seen |= commenters.keys()

        logging.debug("Found %s commenters in %s target",
                      len(commenters), self.short_name)

    def we_can_handle_it(self):
        """Return whether we're able to watch the submission"""
        return (not self.submission.is_self) and \
               self.submission.domain.endswith('reddit.com')

    def run(self):
        logging.info("Watching submission %s", self.short_name)
        if not self.we_can_handle_it():
            logging.info("Stopping watcher for submission %s: unable to handle it",
                         self.short_name)
            return

        self.target = r.get_submission(self.submission.url)

        nothing_new = 0
        while True:
            logging.debug("SW for %s starts working", self.short_name)

            for user, comments in self.get_recent_commenters():
                if not self.is_member_of_subreddit(user, self.target.subreddit):
                    self.popcorn_pissers.append((user, comments))
                    logging.debug("Found a popcorn pisser: %s!", user.name)

            logging.info("Found %s popcorn pissers in thread %s",
                         len(self.popcorn_pissers), self.short_name)
            if len(self.popcorn_pissers) == 0:
                nothing_new += 1
            else:
                self.generate_report()

            if nothing_new == 5:
                # 5 times without any new popcorn pisser = we stop
                logging.info("Nothing's pissing in %s anymore. Stopping.",
                             self.short_name)
                return

            sleep(30 * 60)

    def generate_report(self):
        logging.info("Writing a report for submissions %s",
                     self.short_name)
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
                s.write("[%s](%s) " % (i + 1, c))
            s.write("\n")
        return s.getvalue()

if __name__ == '__main__':
    pp = PopcornPisser()
    pp.start()
