"""CLI dispatch. Historical flag-only invocation still selects `run`."""

import sys

from .parser import build_parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "run")
    args = build_parser().parse_args(argv)
    return args.handler(args, args.command_parser)
