#! /usr/bin/python3

import argparse
import ndiff
import os
from subprocess import Popen, PIPE
import sys
from syslog import openlog, syslog, LOG_PID, LOG_PERROR, LOG_LOCAL7, LOG_DEBUG, LOG_ERR
import tempfile

def main():
    openlog(os.path.basename(__file__), LOG_PID | LOG_PERROR, LOG_LOCAL7)
    #syslog(LOG_DEBUG, f"argv={len(sys.argv)} argv={sys.argv}")
    if len(sys.argv) != 8:
        print(f"{sys.argv}")
        return 0

    parser = argparse.ArgumentParser()

    parser.add_argument("pretty")

    parser.add_argument("file_a")
    parser.add_argument("hash_a")
    parser.add_argument("mode_a")

    parser.add_argument("file_b")
    parser.add_argument("hash_b")
    parser.add_argument("mode_b")

    #syslog(LOG_DEBUG, f"{args.pretty}")
    #syslog(LOG_DEBUG, f"{args.file_a}")
    #syslog(LOG_DEBUG, f"{args.hash_a}")
    #syslog(LOG_DEBUG, f"{args.mode_a}")
    #syslog(LOG_DEBUG, f"{args.file_b}")
    #syslog(LOG_DEBUG, f"{args.hash_b}")
    #syslog(LOG_DEBUG, f"{args.mode_b}")

    args = parser.parse_args()

    if not args.pretty.endswith((".c", ".cc", ".h")) or args.file_a == "/dev/null" or args.file_b == "/dev/null":
        df = diff_files(args.file_a, args.file_b)
    else:
        try:
            with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
                f_name = f.name
            ndiff.ndiff(args.file_a, args.file_b, f_name)
            df = diff_files(f_name, args.file_b)
        finally:
            os.unlink(f_name)

    pretty = args.pretty.encode()
    index_a = args.hash_a[:8].encode()
    index_b = args.hash_b[:8].encode()
    mode = f"{args.mode_b}".encode()

    sys.stdout.buffer.write(b"diff -up a/" + pretty + b" b/" + pretty + b"\n")
    sys.stdout.buffer.write(b"index " + index_a + b".." + index_b + b" " + mode +  b"\n")
    sys.stdout.buffer.write(b"--- a/" + pretty + b"\n")
    sys.stdout.buffer.write(b"+++ b/" + pretty + b"\n")
    for e in df[2:]:
        sys.stdout.buffer.write(e)

    return 0


def diff_files(file_a, file_b):
    cmd = ["diff", "-up", file_a, file_b]
    with Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE) as p:
        try:
            (out, err) = p.communicate()
            p.wait()
        except Exception as e:
            syslog(LOG_ERR, f"{e}")
            raise
    return ndiff.split_bytes(out)
    #return out.splitlines(keepends=True)


if __name__ == "__main__":
    main()
