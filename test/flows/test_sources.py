from ... import flows
from .. import library as testlib

def test_Iteration(test):
	ctx, S = testlib.sector()
	c = flows.Collection.list()
	e = S.CONTROLLER

	i = flows.Iteration(range(100))
	S.dispatch(c)
	S.dispatch(i)
	i.f_connect(c)
	ctx.flush()

	test/c.c_storage == list(range(100))
	test/i.terminated == True

if __name__ == '__main__':
	import sys; from ....test import library as libtest
	libtest.execute(sys.modules['__main__'])
