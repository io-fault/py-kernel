import collections
import functools
import importlib.util
import typing
import itertools

from ... import library
from ... import system
from .. import library as testlib

def test_KInput(test):
	ctx = testlib.Executable()
	c = testlib.SystemChannel()
	f = system.KInput(c)
	f.system = ctx
	f.executable = ctx

	f.actuate()
	test/c.link == f
	f.k_transition()

	# test that allocation is occurring after transition.
	test/f.k_transferring == len(c.resource)
	rlen = len(c.resource)
	test/rlen > 0
	test/f.k_transferring == rlen

def test_KOutput(test):
	ctx = testlib.Executable()
	c = testlib.SystemChannel()
	f = system.KOutput(c)
	f.executable = ctx
	f.system = ctx

	f.actuate()
	test/f.channel == c
	test/c.link == f

	# nothing has been allocated
	f.f_transfer((b'datas',))
	test/f.k_transferring == len(c.resource)
	test/f.k_transferring == 5

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
