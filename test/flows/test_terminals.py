import collections
import functools
import importlib.util
import typing
import itertools

from ... import flows
from .. import library as testlib

def test_Collection(test):
	ctx = testlib.Context()
	exit = testlib.ExitController()

	c = flows.Collection.dict()
	c.controller = exit
	c.context = ctx

	f = flows.Channel()
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
		f.process(x)

	test/c.c_storage == {1:"value1",2:"override",3:"value3","string-key":1}

	c = flows.Collection.set()
	c.controller = exit
	c.context = ctx

	f = flows.Channel()
	f.controller = exit
	f.context = ctx
	f.actuate()
	f.f_connect(c)

	events = [1, 2, 3, 3, 3, 4, 5]
	for x in events:
		f.process(x)

	test/sorted(list(c.c_storage)) == [1,2,3,4,5]

	b = flows.Collection.buffer()
	b.actuate()
	b.process([b'data', b' ', b'more'])
	test/b.c_storage == b'data more'

if __name__ == '__main__':
	import sys; from ....test import library as libtest
	libtest.execute(sys.modules['__main__'])
