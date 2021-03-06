#!/usr/bin/env python
"""
    Reynir: Natural language processing for Icelandic

    Trigrams module

    Copyright (c) 2017 Miðeind ehf

       This program is free software: you can redistribute it and/or modify
       it under the terms of the GNU General Public License as published by
       the Free Software Foundation, either version 3 of the License, or
       (at your option) any later version.
       This program is distributed in the hope that it will be useful,
       but WITHOUT ANY WARRANTY; without even the implied warranty of
       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
       GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see http://www.gnu.org/licenses/.

    This module reads parse trees from stored articles and processes the words therein,
    to create trigram lists and statistical data.

"""

import os
import sys
from itertools import islice, tee
from contextlib import closing
from random import randint
import json

# Hack to make this Python program executable from the utils subdirectory
if __name__ == "__main__":
    basepath, _ = os.path.split(os.path.realpath(__file__))
    if basepath.endswith("/utils") or basepath.endswith("\\utils"):
        basepath = basepath[0:-6]
        sys.path.append(basepath)
else:
    basepath = ""

from settings import Settings, ConfigError, Prepositions
from tokenizer import tokenize, correct_spaces, canonicalize_token, TOK
from bindb import BIN_Db
from scraperdb import SessionContext, Article, Trigram, DatabaseError, desc
from tree import TreeTokenList, TerminalDescriptor


def dump_tokens(limit):
    """ Iterate through parsed articles and print a list
        of tokens and their matched terminals """

    dtd = dict()
    with BIN_Db.get_db() as db, SessionContext(commit = True) as session:
        # Iterate through the articles
        q = session.query(Article) \
            .filter(Article.tree != None) \
            .order_by(Article.timestamp)
        if limit is None:
            q = q.all()
        else:
            q = q[0:limit]
        for a in q:
            print("\nARTICLE\nHeading: '{0.heading}'\nURL: {0.url}\nTimestamp: {0.timestamp}".format(a))
            tree = TreeTokenList()
            tree.load(a.tree)
            for ix, toklist in tree.sentences():
                print("\nSentence {0}:".format(ix))
                at_start = True
                for t in toklist:
                    if t.tokentype == "WORD":
                        wrd = t.token[1:-1]
                        td = dtd.get(t.terminal)
                        if td is None:
                            td = TerminalDescriptor(t.terminal)
                            dtd[t.terminal] = td
                        stem = td.stem(db, wrd, at_start)
                        at_start = False
                        print("    {0} {1} {2}".format(wrd, stem, t.terminal))
                    else:
                        print("    {0.token} {0.cat} {0.terminal}".format(t))


def make_trigrams(limit):
    """ Iterate through parsed articles and extract trigrams from
        successfully parsed sentences """

    with SessionContext(commit = True) as session:

        # Delete existing trigrams
        Trigram.delete_all(session)
        # Iterate through the articles
        q = session.query(Article.url, Article.timestamp, Article.tree) \
            .filter(Article.tree != None) \
            .order_by(Article.timestamp)
        if limit is None:
            q = q.yield_per(200)
        else:
            q = q[0:limit]

        def tokens(q):
            """ Generator for token stream """
            for a in q:
                print("Processing article from {0.timestamp}: {0.url}".format(a))
                tree = TreeTokenList()
                tree.load(a.tree)
                for ix, toklist in tree.sentences():
                    if toklist:
                        # For each sentence, start and end with empty strings
                        yield ""
                        yield ""
                        for t in toklist:
                            yield t.token[1:-1]
                        yield ""
                        yield ""

        def trigrams(iterable):
            return zip(*((islice(seq, i, None) for i, seq in enumerate(tee(iterable, 3)))))

        FLUSH_THRESHOLD = 0 # 200 # Flush once every 200 records
        cnt = 0
        for tg in trigrams(tokens(q)):
            # print("{0}".format(tg))
            if any(w for w in tg):
                try:
                    Trigram.upsert(session, *tg)
                    cnt += 1
                    if cnt == FLUSH_THRESHOLD:
                        session.flush()
                        cnt = 0
                except DatabaseError as ex:
                    print("*** Exception {0} on trigram {1}, skipped".format(ex, tg))


def spin_trigrams(num):
    """ Spin random sentences out of trigrams """

    with SessionContext(commit = True) as session:
        print("Loading first candidates")
        q = session.execute(
            "select t3, frequency from trigrams where t1='' and t2='' order by frequency desc"
        )
        # DEBUG
        #from sqlalchemy.dialects import postgresql
        #print(str(q.statement.compile(dialect=postgresql.dialect())))
        # DEBUG
        first = q.fetchall()
        print("{0} first candidates loaded".format(len(first)))

        def spin_trigram(first):
            t1 = t2 = ""
            candidates = first
            sent = ""
            while candidates:
                sumfreq = sum(freq for _, freq in candidates)
                r = randint(0, sumfreq - 1)
                for t3, freq in candidates:
                    if r < freq:
                        if not t3:
                            # End of sentence
                            candidates = []
                            break
                        if sent:
                            sent += ' ' + t3
                        else:
                            sent = t3
                        t1, t2 = t2, t3
                        q = session.execute(
                            "select t3, frequency from trigrams where t1=:t1 and t2=:t2 order by frequency desc",
                            dict(t1 = t1, t2 = t2)
                        )
                        candidates = q.fetchall()
                        break
                    r -= freq
            return correct_spaces(sent)

        # Spin the sentences
        for i in range(num):
            print("{0}".format(spin_trigram(first)))


def main():

    try:
        # Read configuration file
        Settings.read(os.path.join(basepath, "config/ReynirSimple.conf"))
    except ConfigError as e:
        print("Configuration error: {0}".format(e))
        quit()

    #make_trigrams(limit = None)
    #dump_tokens(limit = 10)

    spin_trigrams(25)


if __name__ == "__main__":

    main()
