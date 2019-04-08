import collections
import functools
import importlib.util
import typing
import itertools

from ... import flows as library
from .. import library as testlib

def test_Terminal(test):
	"""
	# Check that terminals don't stop events (trailing processors).
	# Check that f_terminate performs the designated callback.
	"""
	called = False
	arg = None
	def callback(flow):
		nonlocal called, arg
		called = True
		arg = flow

	ctx = testlib.Executable()
	exit = testlib.ExitController()
	t = library.Terminal(callback)
	t.controller = exit
	t.executable = ctx
	t.actuate()

	test/called == False
	test/arg == None

	# Validate continuation; terminals dont stop transfers despite the contradiction.
	l = []
	def append(i, **kw):
		nonlocal l
		l.append(i)
	t.f_emit = append
	t.f_transfer('test')
	test/l[0] == 'test'

	# Primary functionality; callback performed at termination.
	t.f_terminate()
	test/t.terminated == True
	test/called == True
	test/arg == t

def test_Collection(test):
	ctx = testlib.Executable()
	exit = testlib.ExitController()

	c = library.Collection.dict()
	c.controller = exit
	c.executable = ctx

	f = library.Channel()
	f.controller = exit
	f.context = ctx
	f.actuate()
	f.f_connect(c)

	events = [
		(1, "value1"),
		(2, "value2"),
		(3, "value3"),
		(2, "override"),
		("string-key", 0),
		("string-key", 1),
	]
	for x in events:
		f.f_transfer(x)

	test/c.c_storage == {1:"value1",2:"override",3:"value3","string-key":1}

	c = library.Collection.set()
	c.controller = exit
	c.context = ctx

	f = library.Channel()
	f.controller = exit
	f.context = ctx
	f.actuate()
	f.f_connect(c)

	events = [1, 2, 3, 3, 3, 4, 5]
	for x in events:
		f.f_transfer(x)

	test/sorted(list(c.c_storage)) == [1,2,3,4,5]

	b = library.Collection.buffer()
	b.actuate()
	b.f_transfer([b'data', b' ', b'more'])
	test/b.c_storage == b'data more'

if __name__ == '__main__':
	import sys; from ....test import library as libtest
	libtest.execute(sys.modules['__main__'])
