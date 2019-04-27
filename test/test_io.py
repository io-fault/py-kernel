"""
# Validate Transfer and Transport sanity.
"""
import collections
import functools
import typing
import itertools

from . import library as testlib
from .. import flows
from .. import core
from .. import io

def test_Transfer_io_flow(test):
	ctx, S = testlib.sector()
	xact = core.Transaction.create(io.Transfer())
	S.dispatch(xact)
	ctx()

	c = flows.Collection.list()
	i = flows.Iteration(range(100))
	xact.xact_context.io_flow([i, c])
	test/xact.xact_context.terminating == False
	ctx()

	test/xact.xact_context.terminating == True
	test/c.c_storage == list(range(100))
	test/xact.xact_context.terminated == False
	ctx()
	test/xact.xact_context.terminated == True

def test_Transport_tp_connect(test):
	ctx, S = testlib.sector()
	i = [
		(flows.fe_initiate, 1, None),
		(flows.fe_transfer, 1, 1),
		(flows.fe_transfer, 1, 2),
		(flows.fe_transfer, 1, 3),
		(flows.fe_terminate, 1, None),
	]
	first = 'initial', (flows.Iteration([i]), flows.Collection.list())
	stack = [first]

	xact = core.Transaction.create(io.Transport.from_stack(stack))
	S.dispatch(xact)
	ctx()
	mitre = flows.Channel()
	xact.xact_context.tp_connect(mitre)
	test/first[1][1].c_storage == []
	ctx()
	test/first[1][1].c_storage == [i]

	test/xact.xact_context.terminating == True
	ctx()
	test/xact.xact_context.terminated == True

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
