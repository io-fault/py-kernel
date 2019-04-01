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
	Type = flows.Event

	test/Type.initiate != Type.terminate
	test/Type.clear != Type.obstruct
	test/Type.initiate == Type.initiate

	test/str(Type.initiate) == 'initiate'
	test/repr(Type.initiate) == 'Event.initiate'

	test/int(Type.initiate) == 2
	test/int(Type.transfer) == 0
	test/int(Type.terminate) == -2

def test_Catenation(test):
	"""
	# Subflow sequencing tests.
	"""

	Type = flows.Catenation
	fc_terminate = flows.Event.terminate
	fc_initiate = flows.Event.initiate
	fc_transfer = flows.Event.transfer
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

	# reserve slots
	x.cat_reserve(1)
	x.cat_reserve(2)
	x.cat_connect(2, i2) # validate blocking of 1

	x.cat_reserve(3)
	i3.f_obstruct(test, None)

	# Data sent to the flow should be enqueued.
	# with test.annotate("enqueued flows do not emit")
	S.dispatch(i2)
	ctx.flush()
	test/c.c_storage == []
	test/len(x.cat_connections[i2][0]) > 0
	test/i2.f_obstructed == True

	# connect fi, but don't transfer anything yet.
	x.cat_connect(1, i1)
	ctx.flush()
	test/c.c_storage[0] == [(fc_initiate, 1)]
	del c.c_storage[:]
	test/x.cat_connections[i1][0] == None # head of line shouldn't have queue.

	x.cat_connect(3, i3)
	S.dispatch(i3)
	ctx.flush()
	test/c.c_storage == [] # i3 is not yet hol and...
	# i3 is obstructed prior to cat_connect; queue should be empty.
	test/list(x.cat_connections[i3][0]) == []

	test/i2.f_obstructed == True # Still obstructed by i1.
	# Check obstruction occurrence from enqueued transfers.
	obc = i2.f_obstructions[x][1]
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
	expect.append((fc_terminate, 1))
	expect.append((fc_initiate, 2))
	expect.extend(zip(itertools.repeat(fc_transfer), itertools.repeat(2), range(100)))
	expect.append((fc_terminate, 2))
	expect.append((fc_initiate, 3))

	test/list(itertools.chain.from_iterable(c.c_storage)) == expect
	test/i2.terminated == True
	del c.c_storage[:]

	test/x.terminated == False
	# termination completes when queue is empty.
	x.f_terminate(test)
	test/x.terminated == False

	# i3 was obstructed prior to cat_connect meaning, the queue
	# should be empty. It was connected after x.cat_connect(1, i1).
	test/x.cat_connections[i3][0] == None
	i3.f_clear(test)
	ctx.flush()
	expect = list(zip(itertools.repeat(fc_transfer), itertools.repeat(3), range(100, 200, 2)))
	expect.append((fc_terminate, 3))
	test/list(itertools.chain.from_iterable(c.c_storage)) == expect
	test/i3.terminated == True

	ctx()
	test/x.terminated == True
	test/x_exit == [x]

def test_Division(test):
	"""
	# Subflow siphoning.
	"""

	fc_xfer = flows.Event.transfer
	fc_terminate = flows.Event.terminate
	fc_init = flows.Event.initiate

	Type = flows.Division
	ctx, S = testlib.sector()

	class Local(flows.Mitre):
		accepted = []
		def f_transfer(self, requests, source=None):
			responses = self.f_emit(Layer() for x in requests)
			# received connection
			self.accepted.extend(requests)

	x = Type()
	mitre = Local()
	S.dispatch(mitre)
	S.dispatch(x)
	x.f_connect(mitre)

	# no content
	x.f_transfer([(fc_init, 1)])
	ctx()
	test/mitre.accepted[0][0] == 1
	ctx()

	test.isinstance(mitre.accepted[0][1], typing.Callable)
	c = flows.Collection.list()
	S.dispatch(c)
	x.f_transfer([(fc_xfer, 1, (b'data',))])
	x.div_connect(1, c)
	test/c.c_storage == [(b'data',)]
	test/c.terminated == False
	x.f_transfer([(fc_terminate, 1)])
	ctx()
	test/c.terminated == True

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
