from ... import library
from ... import flows
from .. import library as testlib

def test_Iteration(test):
	ctx, S = testlib.sector()
	c = flows.Collection.list()
	e = S.CONTROLLER

	i = flows.Iteration(range(100))
	S.dispatch(i)
	i.f_connect(c)
	i.actuate()
	ctx.flush()

	test/c.c_storage == list(range(100))
	test/i.terminated == True

def test_Iteration_null_terminal(test):
	ctx, S = testlib.sector()
	e = S.CONTROLLER
	i = flows.Iteration(range(100))
	i.f_connect(flows.null)
	S.dispatch(i)
	ctx.flush()
	# Validate empty iterator.
	test/tuple(i.it_iterator) == ()

if __name__ == '__main__':
	import sys; from ....test import library as libtest
	libtest.execute(sys.modules['__main__'])
