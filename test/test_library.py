import collections
import functools
import importlib.util
import typing
import itertools

from .. import library
from .. import flows
from .. import command
from . import library as testlib

def test_parallel(test):
	return
	t = False
	def nothing(*args):
		nonlocal t
		t = True

	i = functools.partial(command.initialize, main=nothing)

	try:
		with library.parallel(i) as unit:
			pass
	except KeyError:
		# There's a race condition, atm, as
		# the Unit is terminating before it
		# is being selected from the index.
		# If there's a key error, rely on
		# subsequent test to validate success.
		pass
	test/t == True

def test_Lock(test):
	"""
	# Check event driven mutual exclusion. Uses main thread access to synchronize.
	"""

	s = library.Lock()
	cell = []
	def inc(release):
		cell.append(1)
	def dec(release):
		cell.append(-1)

	s.acquire(inc)
	test/sum(cell) == 1
	s.acquire(dec)
	s.release()
	test/sum(cell) == 0

def test_fault(test):
	"""
	# Check interrupt effect of faulting.
	"""
	ctx, s = testlib.sector()
	f = library.Fatal()
	f1 = flows.Channel()
	s.dispatch(f1)
	s.dispatch(f)
	ctx.flush()
	test/s.interruptor == f
	test/f1.interrupted == True
	test/s.interrupted == True
	test/bool(f.exceptions) == True

def setup_connected_flows():
	ctx, usector, dsector = testlib.sector(2)

	us = flows.Channel()
	ds = flows.Collection.list()
	usector.dispatch(us)
	dsector.dispatch(ds)

	return usector, dsector, ds.c_storage, us, ds

def test_Flow_connect_events(test):
	"""
	# Validate events of connected Flows across Sector boundaries.
	"""
	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.f_connect(ds)

	test/us.f_downstream is ds
	test/us.functioning == True
	test/ds.functioning == True
	us.process(1)
	test/reservoir == [1]

	# validate that terminate is inherited
	us.terminate()
	us.context()
	test/us.terminated == True
	usector.context()
	test/ds.terminated == True

	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.f_connect(ds)

	# faulted flow
	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.f_connect(ds)

	# validate that interrupt is inherited
	us.fault(Exception("int"))
	usector.context() # context is shared
	test/us.interrupted == True
	test/ds.interrupted == False

	# The downstream should have had its exit signalled
	# which means the controlling sector should have
	# exited as well.
	dsector.context()
	test/dsector.terminated == True

def test_Call(test):
	Type = library.Call
	ctx, sect = testlib.sector()

	arg = object()
	kw = object()

	effects = []
	def call_to_perform(arg1, key=None):
		effects.append(arg1)
		effects.append(key)
		effects.append(library.context().sector)
		effects.append('called')

	c = Type.partial(call_to_perform, arg, key=kw)
	sect.dispatch(c)

	ctx()

	test/effects[0] == arg
	test/effects[1] == kw
	test/effects[-1] == 'called'
	test/effects[-2] == sect

def test_Coroutine(test):
	"""
	# Evaluate the functions of a &library.Coroutine process;
	# notably the continuations and callback registration.
	"""
	Type = library.Coroutine
	ctx, sect = testlib.sector()
	return

	effects = []

	@typing.coroutine
	def coroutine_to_execute(sector):
		yield None
		effects.append(sector)
		effects.append('called')

	co = Type(coroutine_to_execute)
	sect.dispatch(co)
	ctx()

	test/effects[-1] == 'called'
	test/effects[0] == sect

def test_KInput(test):
	ctx = testlib.Context()
	t = testlib.SystemChannel()
	f = flows.KInput(t)

	f.context = ctx
	f.actuate()
	test/t.link == f
	f.k_transition()

	# test that allocation is occurring after transition.
	test/f.k_transferring == len(t.resource)
	rlen = len(t.resource)
	test/rlen > 0
	test/f.k_transferring == rlen

def test_KOutput(test):
	ctx = testlib.Context()
	t = testlib.SystemChannel()
	f = flows.KOutput(t)
	f.context = ctx
	f.actuate()
	test/f.transit == t
	test/t.link == f

	# nothing has been allocated
	f.process((b'datas',))
	test/f.k_transferring == len(t.resource)

def test_Transformation(test):
	ctx = testlib.Context()
	i = 0
	def f(event):
		nonlocal i
		i = i + 1
		return event+1
	t = flows.Transformation(f)
	c = flows.Collection.list()
	t.context = ctx
	c.context = ctx
	t.f_connect(c)

	t.process(10)
	test/i == 1
	t.process(20)
	test/i == 2
	t.process(30)
	test/i == 3

	t.terminate()
	test/t.terminated == True
	test/c.c_storage == [11,21,31]
	ctx()
	test/c.terminated == True

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
