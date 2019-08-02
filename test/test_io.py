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
from .. import io as module

def test_Transfer_io_flow(test):
	ctx, S = testlib.sector()
	xact = core.Transaction.create(module.Transfer())
	S.dispatch(xact)
	ctx(1)

	c = flows.Collection.list()
	i = flows.Iteration(range(100))
	xact.xact_context.io_flow([i, c])
	test/xact.xact_context.terminating == False
	ctx(1)

	test/xact.xact_context.terminating == True
	test/c.c_storage == list(range(100))
	test/xact.xact_context.terminated == False
	ctx(1)
	test/xact.xact_context.terminated == True

def test_Invocations_actuate(test):
	"""
	# - &module.Invocations.actuate
	"""

	i = module.Invocations(None, None)
	test/AttributeError ^ i.actuate

	cat = flows.Catenation()
	i = module.Invocations(cat, None)
	i.actuate()

def test_Invocations_allocate(test):
	"""
	# - &module.Invocations.m_allocate
	"""
	target = []
	cat = flows.Catenation()
	inv = module.Invocations(cat, target.extend)
	inv.actuate()

	test/list(inv.m_allocate())[0][0] == 1

def test_Invocations_accept(test):
	"""
	# - &module.Invocations
	"""
	ctx, S = testlib.sector()
	l = []
	cat = flows.Catenation()
	inv = module.Invocations(cat, l.append)
	S.dispatch(cat)
	S.dispatch(inv)

	inv.i_dispatch([(1, 'parameter', None)])
	ctx(1)

	test/l[0] == inv
	accepts, connects = inv.inv_accept()
	test/connects[0] == (1, 'parameter', None)

def test_Transport_tp_connect(test):
	cat = None
	ctx, S = testlib.sector()
	ev = [
		(flows.fe_initiate, 1, None),
		(flows.fe_transfer, 1, 1),
		(flows.fe_transfer, 1, 2),
		(flows.fe_transfer, 1, 3),
		(flows.fe_terminate, 1, None),
	]
	c = flows.Collection.list()
	io = ('initial', None), (flows.Iteration([ev]), c)

	xact = core.Transaction.create(module.Transport.from_endpoint(io))
	S.dispatch(xact)
	ctx(1)

	i = None
	def router(inv):
		nonlocal i
		div = i._io_start().f_downstream.f_downstream

		events = inv.m_correlate()
		inv.i_catenate.f_transfer(events, upstream=div)

	protocol = ('protocol', None), (flows.Channel(), flows.Channel())
	inv = xact.xact_context.tp_connect(router, protocol)
	o = xact.xact_context.tp_output.xact_context
	i = xact.xact_context.tp_input.xact_context

	test/c.c_storage == []
	ctx(2)
	test/i.terminating == True

	ctx(1)
	test/c.c_storage == [ev]
	ctx(1)
	test/i.terminated == True

	test/o.terminating == False
	test/inv.terminated == False
	test/xact.xact_context.terminated == False
	test/xact.terminated == False

	# Terminate output.
	inv.i_catenate.f_terminate()
	test/o.terminating == True
	ctx(1)
	test/o.terminated == True

	ctx(1)
	test/inv.terminated == True
	test/xact.xact_context.terminated == True

	ctx(1)
	test/xact.terminated == True

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
