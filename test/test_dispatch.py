import collections
import functools
import typing
import itertools

from .. import dispatch as library
from .. import flows
from . import library as testlib

def test_Call(test):
	Type = library.Call
	ctx, sect = testlib.sector()

	arg = object()
	kw = object()

	effects = []
	def call_to_perform(arg1, key=None):
		effects.append(arg1)
		effects.append(key)
		effects.append('called')

	c = Type.partial(call_to_perform, arg, key=kw)
	sect.dispatch(c)

	ctx()

	test/effects[0] == arg
	test/effects[1] == kw
	test/effects[-1] == 'called'

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

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
