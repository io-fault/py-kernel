from ..console import core as library

def test_cache(test):
	'clipboard implementation'
	c = library.Cache()

	c.allocate('x')
	c.put('x', ('no-type', ('set',)))
	test/c.get('x') == ('no-type', ('set',))

	c.put('x', ('some-type', 'data'))
	test/c.get('x') == ('some-type', 'data')
	test/c.get('x', 1) == ('no-type', ('set',))

	# check limit
	c.limit = 3
	test/len(c.storage['x']) == 2
	c.put('x', ('other-type', 'data'))
	test/len(c.storage['x']) == 3
	c.put('x', ('yet-other-type', 'data2'))
	test/len(c.storage['x']) == 3 # exceeded limit

	test/c.get('x') == ('yet-other-type', 'data2')
	test/c.get('x', 1) == ('other-type', 'data')
	test/c.get('x', 2) == ('some-type', 'data')

if __name__ == '__main__':
	from ...development import libtest
	import sys; libtest.execute(sys.modules[__name__])
