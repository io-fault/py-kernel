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

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
