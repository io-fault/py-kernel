from .. import lib

if __name__ == '__main__':
	import sys; from ...dev import libtest
	libtest.execute(sys.modules[__name__])
