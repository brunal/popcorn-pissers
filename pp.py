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

from enum import Enum
import praw


def setup_logging():
    pp_logging = log.getLogger('bru.pp')
    pp_logging.setLevel(log.DEBUG)

    stderr = log.StreamHandler()
    stderr.setLevel(log.INFO)
    pp_logging.addHandler(stderr)

    to_file = log.FileHandler('log.txt')
    to_file.setLevel(log.DEBUG)
    pp_logging.addHandler(to_file)

    return pp_logging

logging = setup_logging()
logging.debug("Loggers configured")


@total_ordering
class OrderedComment(praw.objects.Comment):
    """Comment with sort on creation date

    Parameters
    ----------
    comment : praw.objects.Comment
        Original comment object. Shares state with `self`
    """

    def __init__(self, comment):
        self.__dict__ = comment.__dict__

    def __gt__(self, other):
        return self.created_utc > other.created_utc

    def __eq__(self, other):
        return self.permalink == other.permalink


def get_config(name='settings.txt'):
    config = ConfigParser()
    config.read(name)
    return config


def reddit_instance(config):
    r = praw.Reddit("popcorn-pissers by /u/Laugarhraun")
    r.login(config.get('auth', 'username'),
            config.get('auth', 'password'))
    logging.info("Bot logged in")

    subreddit_name = config.get('subreddit', 'subreddit')
    s = r.get_subreddit(subreddit_name)

    return r, s


class PopcornPisser(Thread):
    """Indefinitely look for new submissions and watch them

    Parameters
    ----------
    reddit : praw.objects.Reddit
    subreddit : praw.objects.Subreddit

    Attributes
    ----------
    reddit : praw.objects.Reddit
    subreddit : praw.objects.Subreddit
    submissions_seen : set of praw.objects.Submission
    """
    def __init__(self, reddit, subreddit):
        super(PopcornPisser, self).__init__()
        self.submissions_seen = set()
        self.reddit = reddit
        self.subreddit = subreddit

    def get_submissions_to_watch(self):
        """Get hot submissions that haven't been treated

        Returns
        -------
        hot_and_new : praw.objects.Submission list
        """
        hot = self.subreddit.get_hot(limit=10)
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
    """Watch a single reddit thread

    Parameters
    ----------
    submission : praw.objects.Submission

    Attributes
    ----------
    submission, target : praw.objects.Submission
    short_name : str
    popcorn_pissers : list of praw.objects.Redditor
    commenters_seen : list of praw.objects.Redditor
    comment_posted : praw.objects.Comment
    """
    def __init__(self, submission):
        super(SubmissionWatcher, self).__init__()

        self.submission = submission
        self.target = None  # load it later, in its own thread
        self.short_name = submission.short_link

        self.popcorn_pissers = []
        self.commenters_seen = set()

        self.comment_posted = None

    def get_recent_commenters(self):
        """Get all commenters after submission creation and their comments

        We need to handle the comments from oldest to youngest, so that if a
        redditor posted before and after the thread submission he's always
        cleared. We need quick oldest retrieval and insertion of comment so
        we use a heap.

        We use OrderedComment objects instead of praw.objects.Comment objects for
        an ordering on utc creation date."""
        logging.debug("Looking for commenters in %s target", self.short_name)

        commenters = dict()  # author name to author-comments dict
        comments = heapq.heapify(map(OrderedComment, self.target.comments))
        while len(comments):
            logging.debug("%s: %s users seen, %s messages left to do",
                          self.short_name, len(commenters), len(comments))

            c = heapq.heappop(comments)
            try:
                for c_ in c.replies:
                    heapq.heappush(comments, OrderedComment(c_))
            except AttributeError:
                # we have a MoreComments object
                try:
                    for c_ in c.comments():
                        heapq.heappush(comments, OrderedComment(c_))
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

        # FIXME: submission target may be a comment; does that work?
        r = self.submission.reddit_session
        self.target = r.get_submission(self.submission.url)

        nothing_new = 0
        while True:
            logging.debug("SW for %s starts working", self.short_name)

            for user, comments in self.get_recent_commenters():
                m = Membership(self.submission.subreddit, self.target, user)
                if m.category is not Membership.Category.THERE:
                    self.popcorn_pissers.append((m, comments))
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
        s.write("I found popcorn pissers in the thread:\n\n")
        # order by category
        by_category = {mem.category: (mem, comments)
                       for mem, comments in self.popcorn_pissers}
        for category in [Membership.Category.HERE,
                         Membership.Category.NO,
                         Membership.Category.BOTH]:
            s.write("Those redditors are %s" % category)
            for mem, comments in by_category[category]:
                s.write("* /u/%s: " % mem.redditor)
                for i, c in enumerate(comments):
                    s.write("[%s](%s) " % (i + 1, c))
                s.write("\n")
        return s.getvalue()


class Membership(object):
    """Determine whether `redditor` is pissing in the popcorn.

    That check is more tricky than it might seem: if `redditor` previously
    pissed in the popcorn in `subreddit` he may be seen as a member.

    A `score` is established for each redditor and a `category` is assigned,
    depending on what was found: whether he posted in target,
    origin subreddits, etc.

    There is room for a lot of improvement

    Parameters
    ----------
    origin_subreddit : praw.objects.Subreddit
    target : praw.objects.Submission
    redditor : praw.objects.Redditor
        A redditor who commented in target thread
    """

    class Category(Enum):
        NO = 0b00
        THERE = 0b01
        HERE = 0b10
        BOTH = 0b11

        def __str__(self):
            return {self.NO: "not active here nor there",
                    self.THERE: "active only there",
                    self.HERE: "active only here",
                    self.BOTH: "active both here and there"}[self]

    def __init__(self, origin_subreddit, target, redditor):
        self.target = target
        self.target_subreddit = target.subreddit
        self.origin_subreddit = origin_subreddit
        self.redditor = redditor

        self.target_activity = []
        self.origin_activity = []

        self._retrieve_activity()

    @property
    def category(self):
        return self.Category(self.Category.THERE.value * self.active_in_target +
                             self.Category.HERE.value * self.active_in_origin)

    @property
    def score(self):
        return 0

    @property
    def active_in_origin(self):
        return bool(self.origin_activity)

    @property
    def active_in_target(self):
        return bool(self.target_activity)

    def _retrieve_activity(self):
        overview = self.redditor.get_overview(limit=100)
        map(self._compute_influence_of, overview)

    def _compute_influence_of(self, action):
        if action.subreddit == self.origin_subreddit:
            # happens in the origin
            self.origin_activity.append(action.permalink)

        if action.subreddit == self.target_subreddit:
            # happens in the target
            try:
                # Is it an early comment from the target thread?
                if action.submission != self.target \
                   or action.created_utc < action.submission.created_utc:
                    # no it's not / yet it is but it is older
                    self.target_activity.append(action.permalink)
                    logging.debug("%s cleared by comment %s",
                                  self.redditor.name, action.permalink)
            except AttributeError:
                # `redditor` submitted something in `subreddit`
                self.target_activity.append(action.permalink)
                logging.debug("%s cleared by item %s",
                              self.redditor.name, action)


def main():
    config = get_config()
    reddit, subreddit = reddit_instance(config)
    pp = PopcornPisser(reddit, subreddit)
    pp.start()


if __name__ == '__main__':
    main()
