#! /usr/local/bin/python3

import argparse
from collections import namedtuple
import os
import re
from subprocess import Popen, PIPE
import sys
from syslog import openlog, syslog, LOG_PID, LOG_PERROR, LOG_LOCAL7, LOG_DEBUG, LOG_ERR
import tempfile


Changed =   namedtuple("Changed",   ["diff_command", "a_start", "a_end", "a_lines", "b_start", "b_end", "b_lines"])
Added =     namedtuple("Added",     ["diff_command", "a_start", "a_end", "a_lines", "b_start", "b_end", "b_lines"])
Deleted =   namedtuple("Deleted",   ["diff_command", "a_start", "a_end", "a_lines", "b_start", "b_end", "b_lines"])
Unchanged = namedtuple("Unchanged", ["diff_command", "a_start", "a_end", "a_lines", "b_start", "b_end", "b_lines"])

Sensible =  namedtuple("Sensible",  ["raw_index", "token", "start", "end"])
Token =     namedtuple("Token",     ["token", "start", "end"])


def main():
    openlog(os.path.basename(__file__), LOG_PID | LOG_PERROR, LOG_LOCAL7)
    #syslog(LOG_DEBUG, f"argv={sys.argv}")

    parser = argparse.ArgumentParser()
    parser.add_argument("file_a")
    parser.add_argument("file_b")
    parser.add_argument("file_out")
    args = parser.parse_args()
    ndiff(args.file_a, args.file_b, args.file_out)


def ndiff(file_a, file_b, file_out):
    (r, lines_a, lines_b, raw_a, raw_b) = diff_n(file_a, file_b)
    if r is None:
        with open(file_out, mode="wb") as f:
            f.write(b"Binary files " + file_a.encode() + b" and " + file_b.encode() + b" differ\n")
        return
    a_mid = changelist_to_midway(r, lines_a, lines_b)
    with open(file_out, mode="wb") as f:
        write_tokens_to_file(f, a_mid)


def changelist_to_midway(r, lines_a, lines_b):
    a_mid = []
    for e in r:
        (diff_command, a_start, a_end, a_lines, b_start, b_end, b_lines) = e
        if e.__class__ == Changed:
            #syslog(LOG_DEBUG, f"@@@ CHANGED {e}")
            (a_midway, b_midway) = changed(e)
            a_mid += a_midway
        elif e.__class__ == Added:
            #syslog(LOG_DEBUG, f"@@@ ADDED {e}")
            pass
        elif e.__class__ == Unchanged:
            #syslog(LOG_DEBUG, f"@@@ UNCHANGED {e}")
            a_midway = a_lines if a_start > 0 else a_lines[1:]
            if a_end == len(lines_a):
                a_midway = a_midway[:-1]
            a_mid += a_midway
        elif e.__class__ == Deleted:
            #syslog(LOG_DEBUG, f"@@@ DELETED {e}")
            a_midway = a_lines if a_start > 0 else a_lines[1:]
            if a_end == len(lines_a):
                a_midway = a_midway[:-1]
            a_mid += a_midway
        else:
            raise Exception("Internal Error")
    return a_mid


def diff_n(file_a, file_b):
    (raw_a, lines_a) = readfile(file_a)
    (raw_b, lines_b) = readfile(file_b)
    cmd = ["diff", "-n", file_a, file_b]
    with Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE) as p:
        try:
            (out, err) = p.communicate()
            p.wait()
        except Exception as e:
            syslog(LOG_ERR, f"{e}")
            raise
    return (rcs_format_to_changelist(out, lines_a, lines_b, raw_a, raw_b), lines_a, lines_b, raw_a, raw_b)


def readfile(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
            #f.seek(0)
            #lines0 = f.readlines()                   ## preserve '\n'
            #lines0 = s.strip().splitlines()   ## strip '\n'
            #lines = [e for e in re.split(br'([^\n]+\n)', s) if e != b''] ## keep '\r'
            #lines = s.split(b'\n')
            #lines = [e for e in re.split(br'([^\n]+\n)', s) if e != b''] ## keep '\r'
            lines = split_bytes(raw)
            #syslog(LOG_DEBUG, f"{len(lines0)} {len(lines)}")
            #for (e0, e1) in zip(lines0, lines):
            #    if e0 != e1:
            #        syslog(LOG_DEBUG, f"DIFFER: {e0} {e1}")
    except Exception as e:
        syslog(LOG_ERR, f"{e}")
        raise
    def add_sentinel(lines):
        return [b"^\n"] + lines + [b"$\n"]
    return (raw, add_sentinel(lines))


"""
split lines by '\n', and retain '\n'.
'\r' is normal character that has no special meanings.
"""
def split_bytes(s):
    r = []
    l = []
    for c in s:
        l.append(c)
        if c == b'\n'[0]:
            r.append(bytes(l))
            l = []
    if l != []:
        r.append(bytes(l))
    return r


def rcs_format_to_changelist(out, lines_a, lines_b, raw_a, raw_b):
    r = []
    add_n_lines = 0
    added_lines = 0
    #df = out.splitlines(keepends=True)
    df = split_bytes(out)
    b_start = 0
    if len(df) > 0 and df[0].startswith(b"Binary file"):
        return None

    a_end = 0
    b_end = 0
    atype = None
    e = None
    command = None

    for (lineno, e) in enumerate(df):
        if 0 < add_n_lines:
            al.append(e)
            added_lines += 1
            if add_n_lines <= added_lines:
                b_end = b_start + add_n_lines
                if atype == Added:
                    assert add_n_lines == len(al)
                    b_lines = lines_b[b_start:b_end]
                    if not all(compare_list(al, b_lines)):
                        syslog(LOG_DEBUG, f"COMPARE_LIST FAILED {al} {b_lines} while processing {sys.argv}")
                    assert all(compare_list(al, b_lines))
                    r.append(Added(e0, a_start, a_start, [], b_start, b_end, al))
                elif atype == Changed:
                    d = r.pop()
                    (_e1, _a_start, _a_end, _lines, _, _, _) = d
                    assert a_end == _a_end
                    r.append(Changed(_e1 + e0, _a_start, _a_end, _lines, b_start, b_end, al))
                else:
                    raise Exception("Internal Error")
                al = []
                (add_n_lines, added_lines) = (0, 0)

        elif e.startswith(b"a"):
            command = (lineno, e)
            ee = e.split(b' ')
            a_start = int(ee[0][1:])        ## a_start行の次に
            add_n_lines = int(ee[1])        ## add_n_lines行追加
            added_lines = 0

            a_start += 1                    ##

            if a_end == a_start:
                assert r[-1].__class__ == Deleted
                atype = Changed
            else:
                assert a_end < a_start
                b_start = a_start - a_end + b_end
                a_lines = lines_a[a_end:a_start]
                b_lines = lines_b[b_end:b_start]
                assert all(compare_list(a_lines, b_lines))
                r.append(Unchanged(None, a_end, a_start, a_lines, b_end, b_start, b_lines))
                atype = Added
                a_end = a_start
                b_end = b_start
            e0 = e

            al = []
            #a_end = a_start + add_n_lines  ## 変化しない

        elif e.startswith(b"d"):
            command = (lineno, e)
            ee = e.split(b' ')
            a_start = int(ee[0][1:])        ## a_start行から
            delete_n_lines = int(ee[1])     ## delete_n_lines行削除

            if a_end < a_start:
                b_start = a_start - a_end + b_end
                a_lines = lines_a[a_end:a_start]
                b_lines = lines_b[b_end:b_start]
                assert all(compare_list(a_lines, b_lines))
                r.append(Unchanged(None, a_end, a_start, a_lines, b_end, b_start, b_lines))
                a_end = a_start
                b_end = b_start

            a_end = a_start + delete_n_lines
            assert b_start == b_end
            r.append(Deleted(e, a_start, a_end, lines_a[a_start:a_end], b_start, b_start, []))

        else:
            syslog(LOG_DEBUG, f"@@@ G:raw_a={raw_a}")
            syslog(LOG_DEBUG, f"@@@ G:raw_b={raw_b}")
            syslog(LOG_DEBUG, f"@@@ G:raw_a={out}")
            syslog(LOG_DEBUG, f"@@@ G:lines_a={lines_a}")
            syslog(LOG_DEBUG, f"@@@ G:lines_b={lines_b}")
            syslog(LOG_DEBUG, f"@@@ G:df={df}")
            raise Exception(f"GARBAGE command={command} lineno={lineno} garbage_line={e}")

    a_start = len(lines_a)
    if a_end < a_start:
        a_lines = lines_a[a_end:a_start]
        b_start = a_start - a_end + b_end
        b_lines = lines_b[b_end:b_start]
        assert all(compare_list(a_lines, b_lines))
        r.append(Unchanged(None, a_end, a_start, a_lines, b_end, b_start, b_lines))

    a_end = 0
    b_end = 0
    for e in r:
        (diff_command, _a_start, _a_end, _a_lines, _b_start, _b_end, _b_lines) = e
        assert a_end == _a_start
        assert b_end == _b_start
        a_end = _a_end
        b_end = _b_end
    assert a_end == len(lines_a)
    assert b_end == len(lines_b)

    return r


def changed(c):
    #syslog(LOG_DEBUG, f"@@@@@@ CHG: {c}")
    assert c.__class__ == Changed
    (diff_command, a_start, a_end, a_lines, b_start, b_end, b_lines) = c
    #syslog(LOG_DEBUG, f"a_start = {a_start} a_end = {a_end} b_start = {b_start} b_end = {b_end}")

    a_raw_tokens = tokenize(b''.join(a_lines))
    b_raw_tokens = tokenize(b''.join(b_lines))
    a_sensible = [Sensible(i, token, start, end) for (i, (token, start, end)) in enumerate(a_raw_tokens) if not isspaces(token)]
    b_sensible = [Sensible(i, token, start, end) for (i, (token, start, end)) in enumerate(b_raw_tokens) if not isspaces(token)]

    try:
        file_a = write_tokens_to_tempfile([token for (i, token, start, end) in a_sensible], end=b"\n")
        file_b = write_tokens_to_tempfile([token for (i, token, start, end) in b_sensible], end=b"\n")

        #lines_a = readfile(file_a)
        #lines_b = readfile(file_b)
        #lines_a = add_sentinel(a_flat)
        #lines_b = add_sentinel(b_flat)
        #syslog(LOG_DEBUG, f"@@@ COMPARE {compare_list(lines_a, add_sentinel(a_flat))}")
        #syslog(LOG_DEBUG, f"@@@ COMPARE {compare_list(lines_b, add_sentinel(b_flat))}")
        (r, lines_a, lines_b, raw_a, raw_b) = diff_n(file_a, file_b)

    finally:
        os.unlink(file_a)
        os.unlink(file_b)

    def add_sentinel(tokens, raw_tail_index):
        return [Sensible(0, b"^", None, None)] + tokens + [Sensible(raw_tail_index, b"$", None, None)]

    a_sensible_ws = add_sentinel(a_sensible, len(a_raw_tokens))
    b_sensible_ws = add_sentinel(b_sensible, len(b_raw_tokens))

    s_sentinel = Token(b'^', None, None)
    e_sentinel = Token(b'$', None, None)

    a_raw_tokens_ws = [s_sentinel] + a_raw_tokens + [e_sentinel]
    b_raw_tokens_ws = [s_sentinel] + b_raw_tokens + [e_sentinel]

    #syslog(LOG_DEBUG, f"@@@ @@@ @@@ X: a_sensible_ws={a_sensible_ws}")
    #syslog(LOG_DEBUG, f"@@@ @@@ @@@ X: b_sensible_ws={b_sensible_ws}")
    #syslog(LOG_DEBUG, f"@@@ @@@ @@@ X: a_raw_tokens_ws={a_raw_tokens_ws}")
    #syslog(LOG_DEBUG, f"@@@ @@@ @@@ X: b_raw_tokens_ws={b_raw_tokens_ws}")

    prev_a_start = 0
    prev_b_start = 0

    del diff_command, a_start, a_end, a_lines, b_start, b_end, b_lines # foolproof

    a_end = 0
    b_end = 0

    a_out = []
    b_out = []
    raw_a_end = 0
    raw_b_end = 0

    for e in r:
        #syslog(LOG_DEBUG, f"@@@ @@@ @@@ E: {e.__class__.__name__}")
        #syslog(LOG_DEBUG, f"@@@ @@@ @@@ E: a_end={a_end}")
        #syslog(LOG_DEBUG, f"@@@ @@@ @@@ E: b_end={b_end}")
        #syslog(LOG_DEBUG, f"@@@ @@@ @@@ E: e.a_start={e.a_start} e.a_end={e.a_end}")
        #syslog(LOG_DEBUG, f"@@@ @@@ @@@ E: e.a_lines={e.a_lines}")
        #syslog(LOG_DEBUG, f"@@@ @@@ @@@ E: e.b_start={e.b_start} e.b_end={e.b_end}")
        #syslog(LOG_DEBUG, f"@@@ @@@ @@@ E: e.b_lines={e.b_lines}")


        if e.__class__ == Changed:
            #syslog(LOG_DEBUG, f"@@@ C: TOKEN CHANGED {e.a_start}--{e.a_end} => {e.b_start}--{e.b_end}")
            a = a_sensible_ws[e.a_start:e.a_end]
            b = b_sensible_ws[e.b_start:e.b_end]

            raw_a_start = raw_a_end
            raw_a_end = a[-1].raw_index + 2
            #syslog(LOG_DEBUG, f"@@@ C: RAW INDEX A {raw_a_start} {raw_a_end}")
            x = a_raw_tokens_ws[raw_a_start:raw_a_end]
            #syslog(LOG_DEBUG, f"@@@ C: A_LINES             a={e.a_lines}")
            #syslog(LOG_DEBUG, f"@@@ C: A                   a={a}")
            #syslog(LOG_DEBUG, f"@@@ C: RAW TOKEN CHANGED - x={x}")
            x_tokens = [token for (token, start, end) in x]
            a_end = e.a_end
            #syslog(LOG_DEBUG, f"@@@ C: a_out += {x}")
            a_out += x_tokens

            raw_b_start = raw_b_end
            raw_b_end = b[-1].raw_index + 2
            #syslog(LOG_DEBUG, f"@@@ C: RAW INDEX B {raw_b_start} {raw_b_end}")
            x = b_raw_tokens_ws[raw_b_start:raw_b_end]
            #syslog(LOG_DEBUG, f"@@@ C: B_LINES             b={e.b_lines}")
            #syslog(LOG_DEBUG, f"@@@ C: B                   b={b}")
            #syslog(LOG_DEBUG, f"@@@ C: RAW TOKEN CHANGED + x={x}")
            x_tokens = [token for (token, start, end) in x]
            b_end = e.b_end
            b_out += x_tokens

        elif e.__class__ == Added:
            #syslog(LOG_DEBUG, f"@@@ A: TOKEN ADDED {e.a_start} => {e.b_start}--{e.b_end}")
            assert e.a_start == e.a_end
            b = b_sensible_ws[e.b_start:e.b_end]
            raw_b_start = raw_b_end
            raw_b_end = b[-1].raw_index + 2
            #syslog(LOG_DEBUG, f"@@@ A: RAW INDEX B {raw_b_start} {raw_b_end}")
            #syslog(LOG_DEBUG, f"@@@ A: TOKEN ADDED b={b}")
            x = b_raw_tokens_ws[raw_b_start:raw_b_end]
            #syslog(LOG_DEBUG, f"@@@ A: RAW TOKEN ADDED x={x}")
            x_tokens = [token for (token, start, end) in x]
            b_end += e.b_end
            b_out += x_tokens

        elif e.__class__ == Unchanged:
            #syslog(LOG_DEBUG, f"@@@ U: TOKEN UNCHANGED {e.a_start}--{e.a_end} => {e.b_start}--{e.b_end}")
            assert e.a_end - e.a_start == e.b_end - e.b_start
            a = a_sensible_ws[e.a_start:e.a_end]
            b = b_sensible_ws[e.b_start:e.b_end]
            raw_a_start = raw_a_end
            raw_a_end = a[-1].raw_index + 2
            raw_b_start = raw_b_end
            raw_b_end = b[-1].raw_index + 2
            #syslog(LOG_DEBUG, f"@@@ U: RAW INDEX B {raw_b_start} {raw_b_end}")
            #syslog(LOG_DEBUG, f"@@@ U: TOKEN UNCHANGED a={a}")
            #syslog(LOG_DEBUG, f"@@@ U: TOKEN UNCHANGED b={b}")
            assert all(compare_list([e for (i, e, start, end) in a], [e for (i, e, start, end) in b]))
            x = b_raw_tokens_ws[raw_b_start:raw_b_end]
            #syslog(LOG_DEBUG, f"@@@ U: RAW TOKEN UNCHANGED x={x}")
            x_tokens = [token for (token, start, end) in x]
            a_end = e.a_end
            b_end = e.b_end
            #syslog(LOG_DEBUG, f"@@@ U: a_out += {x}")
            a_out += x_tokens  ## b_raw_tokensをa_outに追加する。対応するa_raw_tokensは捨てる。
            b_out += x_tokens

        elif e.__class__ == Deleted:
            #syslog(LOG_DEBUG, f"@@@ D: TOKEN DELETED {e.a_start}--{e.a_end}, b={e.b_start}")
            assert e.b_start == e.b_end
            a = a_sensible_ws[e.a_start:e.a_end]
            raw_a_start = raw_a_end
            raw_a_end = a[-1].raw_index + 2
            #syslog(LOG_DEBUG, f"@@@ D: RAW INDEX A {raw_a_start} {raw_a_end}")
            #syslog(LOG_DEBUG, f"@@@ D: TOKEN DELETED a={a}")
            x = a_raw_tokens_ws[raw_a_start:raw_a_end]
            #syslog(LOG_DEBUG, f"@@@ D: RAW TOKEN DELETED x={x}")
            x_tokens = [token for (token, start, end) in x]
            x_tokens = [token for (token, start, end) in x]
            a_end = e.a_end
            #syslog(LOG_DEBUG, f"@@@ D: a_out += {x}")
            a_out += x_tokens

        else:
            raise Exception("Internal Error")
        assert prev_a_start == e.a_start
        assert prev_b_start == e.b_start
        prev_a_start = e.a_end
        prev_b_start = e.b_end

    # COPY TRAILING INTRON
    raw_b_start = raw_b_end
    raw_b_end = len(b_raw_tokens_ws)
    #syslog(LOG_DEBUG, f"@@@ T: RAW INDEX B {raw_b_start} {raw_b_end}")
    x = b_raw_tokens_ws[raw_b_start:]
    #syslog(LOG_DEBUG, f"@@@ T: RAW TRAILING INTRON x={x}")
    x_tokens = [token for (token, start, end) in x]
    #syslog(LOG_DEBUG, f"@@@ I: a_out += {x}")
    a_out += x_tokens
    b_out += x_tokens

    assert prev_a_start == len(lines_a)
    assert prev_b_start == len(lines_b)

    def strip_sentinel(raw_ws):
        assert raw_ws[0] == b'^'
        assert raw_ws[-1] == b'$'
        return raw_ws[1:][:-1]

    #syslog(LOG_DEBUG, f"@@@ A_OUT {a_out}")
    #syslog(LOG_DEBUG, f"@@@ B_OUT {b_out}")

    #syslog(LOG_DEBUG, f"@@@ A_OUT_WO_S {strip_sentinel(a_out)}")
    #syslog(LOG_DEBUG, f"@@@ B_OUT_WO_S {strip_sentinel(b_out)}")

    a_midway = strip_sentinel(a_out)
    b_midway = strip_sentinel(b_out)

    #syslog(LOG_DEBUG, f"@@@ MIDWAY: {b_midway}")
    #syslog(LOG_DEBUG, f"@@@ EXPECT: {strip_sentinel([e for (e, start, end) in b_raw_tokens_ws])}")
    assert all(compare_list(b_midway, strip_sentinel([e for (e, start, end) in b_raw_tokens_ws])))

    return (a_midway, b_midway)


def flatten_list(a):
    return [e for li in a for e in li]


def write_tokens_to_tempfile(tokens, end=None):
    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        write_tokens_to_file(f, tokens, end)
        return f.name


def write_tokens_to_file(f, tokens, end=None):
    for token in tokens:
        f.write(token)
        if end:
            f.write(end)

def sensible_tokens(tokens):
    return [token for (token, start, end) in tokens if not isspaces(token)]


def isspaces(token):
    for c in token:
        if not isspace(c):
            return False
    return True


def isspace(c):
    return b'\t'[0] == c or b'\n'[0] == c or b'\r'[0] == c or b' '[0] == c


def isalphanumeric(c):
    return (b'a'[0] <= c and c <= b'z'[0] or
            b'A'[0] <= c and c <= b'Z'[0] or
            b'0'[0] <= c and c <= b'9'[0] or
            c == b'_'[0])


def intern(name):
    return (name, )


ucs_first_byte = intern("UCS_1")
ucs_following_byte = intern("UCS_2")
punctuation = intern("PUNCTUATION")
spaces = intern("SPACES")
word_letter = intern("ALPHANUMERIC")


def tokenize(line):
    r = []
    token = []
    def eject(i):
        nonlocal token
        nonlocal start
        if token != []:
            r.append(Token(bytes(token), start, i))
            token = []
            start = i
    prev = None
    start = 0

    for (i, c) in enumerate(line):
        if isspace(c):
            kind = spaces
        elif isalphanumeric(c):
            kind = word_letter
        elif 0x80 <= c and c < 0xc0:
            kind = ucs_following_byte
        elif 0xc0 <= c:
            kind = ucs_first_byte
        else:
            kind = punctuation

        if kind == ucs_following_byte:
            pass
        elif kind == ucs_first_byte or kind == punctuation or kind != prev:
            eject(i)

        prev = kind

        token.append(c)

    eject(i)
    return r


def compare_list(a, b):
    if len(a) != len(b):
        return [False]
    return [e == g for (e, g) in zip(a, b)]


if __name__ == "__main__":
    main()
