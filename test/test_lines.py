from ..console import lines

def test_python(test):
	lines.profile('python')

if __name__ == '__main__':
	import sys; from ...development import libtest
	libtest.execute(sys.modules['__main__'])
