"""
# Miscellaneous flow tests.
"""
import collections
import functools
import typing
import itertools

from ... import flows
from .. import library as testlib

def test_Transformation(test):
	ec = testlib.ExitController()
	ctx = testlib.Executable()
	i = 0
	def f(event):
		nonlocal i
		i = i + 1
		return event+1
	t = flows.Transformation(f)
	t.controller = ec
	c = flows.Collection.list()
	c.controller = ec
	t.executable = ctx
	c.executable = ctx
	t.enqueue = ctx.enqueue
	t.f_connect(c)

	t.f_transfer(10)
	test/i == 1
	t.f_transfer(20)
	test/i == 2
	t.f_transfer(30)
	test/i == 3

	t.f_terminate()
	test/t.terminated == True
	test/c.c_storage == [11,21,31]
	ctx()
	test/c.terminated == True

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
