import collections
import functools
import typing
import itertools

from .. import library
from .. import flows
from . import library as testlib

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
	us.f_transfer(1)
	test/reservoir == [1]

	# validate that terminate is inherited
	us.terminate()
	us.executable()
	test/us.terminated == True
	usector.executable()
	test/ds.terminated == True

	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.f_connect(ds)

	# faulted flow
	usector, dsector, reservoir, us, ds = setup_connected_flows()
	us.f_connect(ds)

	# validate that interrupt is inherited
	us.fault(Exception("int"))
	usector.executable() # context is shared
	test/us.interrupted == True
	test/ds.interrupted == False

	# In this case, the downstream should not be terminated.
	# Interrupts are local to the sector; only intersector connections
	# should propagate termination.
	dsector.executable()
	test/dsector.terminated == False

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
