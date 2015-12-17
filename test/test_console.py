from ..console import core as library

def test_irange(test):
	zero = library.IRange.single(0)
	zero_and_one = library.IRange.normal(0, 1)
	ten = library.IRange.normal(10, 20)

	test/zero == (0,0)
	test/zero_and_one == (0,1)
	test/ten == (10, 20)

	for x in range(0, 1):
		test/x in zero

	for x in range(0, 2):
		test/x in zero_and_one

	for x in range(10, 21):
		test/x in ten

	test/ten.contiguous(library.IRange((21, 30))) == True
	test/ten.contiguous(library.IRange((0, 9))) == True

	test/ten.contiguous(library.IRange((22, 30))) == False
	test/ten.contiguous(library.IRange((0, 8))) == False

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
