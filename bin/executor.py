"""
Execute root nucleus procedures.
"""
import functools
from .. import library as lib
from ...fork import lib as libfork

# Launch a context with a control procedure.

# -P Add a Python module path to sys.path (appends)
# -l mod (derive plans from a particular module or script file)
# -L pkgpath (import pkg module and derive plans)
# -X procedure (execute a concurrent procedure)
# initial arg refers to main procedure.

# python3 -m fault.nucleus.executor -XConsole

def main(exe):
	# Mostly configuration of formalities required by nucleus' environment.
	ctx = lib.Context()
	local = __package__[:__package__.rfind('.')]
	work = lib.__context_index__[ctx]['work']
	work.acquire(local)
	ini = work.library[local + '.stdlib'].Initialize
	t = functools.partial(work.perform, ini, arguments = exe.arguments)
	libfork.control(ctx.boot, t)

if __name__ == '__main__':
	main(libfork.Execution.default())
