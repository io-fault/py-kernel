"""
# Primarily interested in &.flows.Catenation and &.flows.Division;
# tunneling and expansion of flow events.
"""
import collections
import functools
import importlib.util
import typing
import itertools

from ... import flows
from .. import library as testlib

def test_event_identifiers(test):
	"""
	# Validate primitives.
	"""

	test/flows.fe_initiate != flows.fe_terminate
	test/flows.fe_clear != flows.fe_obstruct
	test/flows.fe_initiate == flows.fe_initiate

	test/str(flows.fe_initiate) == 'fe_initiate'
	test/repr(flows.fe_initiate) == 'fe_initiate'

	test/int(flows.fe_initiate) == 2
	test/int(flows.fe_transfer) == 0
	test/int(flows.fe_terminate) == -2

def test_Catenation(test):
	"""
	# Subflow sequencing tests.
	"""

	Type = flows.Catenation
	fc_terminate = flows.fe_terminate
	fc_initiate = flows.fe_initiate
	fc_transfer = flows.fe_transfer
	ctx, S = testlib.sector()

	# output flow
	c = flows.Collection.list()
	x = Type()
	S.dispatch(c)
	S.dispatch(x)
	x.f_connect(c)

	x_exit = []
	x.atexit(x_exit.append)
	# pair of inputs
	i1 = flows.Iteration(range(0, -50, -1))
	i2 = flows.Iteration(range(100))
	i3 = flows.Iteration(range(100, 200, 2))
	in1 = flows.Relay(x, 1)
	in2 = flows.Relay(x, 2)
	in3 = flows.Relay(x, 3)

	i1.f_connect(in1)
	i2.f_connect(in2)
	i3.f_connect(in3)
	S.dispatch(in1)
	S.dispatch(in2)
	S.dispatch(in3)

	# reserve slots
	x.int_reserve(1)
	x.int_reserve(2)
	x.int_connect(2, 2, in2) # validate blocking of 1

	x.int_reserve(3)
	in3.f_obstruct(test, None)

	# Data sent to the flow should be enqueued.
	# with test.annotate("enqueued flows do not emit")
	S.dispatch(i2)
	ctx.flush()
	test/c.c_storage == []
	test/len(x.cat_connections[2][0]) > 0
	test/i2.f_obstructed == True

	# connect i1, but don't transfer anything yet.
	x.int_connect(1, 1, in1)
	ctx.flush()
	test/c.c_storage[0] == [(fc_initiate, 1, 1)]
	del c.c_storage[:]
	test/x.cat_connections[1][0] == None # head of line shouldn't have queue.

	x.int_connect(3, 3, in3)
	S.dispatch(i3)
	ctx.flush()
	test/c.c_storage == [] # i3 is not yet hol and...
	# i3 is obstructed prior to int_connect; queue should be empty.
	test/list(x.cat_connections[3][0]) == []

	test/i2.f_obstructed == True # Still obstructed by i1.
	# Check obstruction occurrence from enqueued transfers.
	obc = in2.f_obstructions[x][1]
	test/obc.focus == x
	test/obc.path == ('cat_overflowing',)

	S.dispatch(i1)
	ctx.flush()
	test/i1.f_obstructed == False
	test/i1.terminated == True
	test/x.terminated == False

	ctx.flush()
	test/i2.terminated == True
	test/i2.f_obstructed == False

	expect = list(zip(itertools.repeat(fc_transfer), itertools.repeat(1), range(0,-50,-1)))
	expect.append((fc_terminate, 1, None))
	expect.append((fc_initiate, 2, 2))
	expect.extend(zip(itertools.repeat(fc_transfer), itertools.repeat(2), range(100)))
	expect.append((fc_terminate, 2, None))
	expect.append((fc_initiate, 3, 3))

	test/list(itertools.chain.from_iterable(c.c_storage)) == expect
	test/i2.terminated == True
	del c.c_storage[:]

	test/x.terminated == False
	# termination completes when queue is empty.
	x.f_terminate()
	test/x.terminated == False

	# i3 was obstructed prior to cat_connect meaning, the queue
	# should be empty. It was connected after x.cat_connect(1, i1).
	test/x.cat_connections[3][0] == None
	in3.f_clear(test)
	ctx.flush()
	expect = list(zip(itertools.repeat(fc_transfer), itertools.repeat(3), range(100, 200, 2)))
	expect.append((fc_terminate, 3, None))
	test/list(itertools.chain.from_iterable(c.c_storage)) == expect
	test/i3.terminated == True

	ctx()
	test/x.terminated == True
	test/x_exit == [x]

def test_Division(test):
	"""
	# - &library.Division
	"""

	accepted = []
	class FakeDispatch(object):
		def i_dispatch(self, events):
			accepted.append(events)

	fc_xfer = flows.fe_transfer
	fc_terminate = flows.fe_terminate
	fc_init = flows.fe_initiate

	Type = flows.Division
	ctx, S = testlib.sector()

	x = Type(FakeDispatch())
	S.dispatch(x)

	# no content
	x.f_transfer([(fc_init, 1, "init-parameter")])
	ctx()
	event = accepted[0][0]
	test/event[0] == 1
	test/event[1] == "init-parameter"
	test.isinstance(event[2], typing.Callable)
	ctx()

	cr = flows.Receiver(None)
	c = flows.Collection.list()
	cr.f_connect(c)
	S.dispatch(c)
	S.dispatch(cr)
	x.f_transfer([(fc_xfer, 1, (b'data',))])
	x.div_connect(1, cr)
	ctx()
	test/c.c_storage == [(b'data',)]
	test/c.terminated == False
	x.f_transfer([(fc_terminate, 1, None)])
	ctx()
	test/c.terminated == True

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
