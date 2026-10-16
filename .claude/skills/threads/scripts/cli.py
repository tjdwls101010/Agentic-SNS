#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read Threads through the logged-in Aside browser: feeds, posts and replies, profiles, search."""
import argparse
import sys

from threads import about, listing, maintenance, search, thread

COMMANDS = {'feed': listing.feed, 'post': thread.post, 'search': search.search, 'about': about.about,
            'doctor': maintenance.doctor}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cli.py', description=__doc__)
    parser.add_argument('command', choices=sorted(COMMANDS))
    options = vars(parser.parse_args(argv))
    return COMMANDS[options['command']](options)


if __name__ == '__main__':
    sys.exit(main())
