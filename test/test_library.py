import functools
from .. import library
from .. import libcommand

def test_parallel(test):
	t = False
	def nothing(*args):
		nonlocal t
		t = True

	i = functools.partial(libcommand.initialize, main=nothing)

	with library.parallel(i) as unit:
		pass
	test/t == True

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules['__main__'])
