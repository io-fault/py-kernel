from .. import libfields as library

def test_segments(test):
	'segementation of line sequences'
	s = library.Segments()
	l = [
		('line1',),
		('line2',),
		('line3',),
	]
	s.insert(0, l)

	l2 = [
		('segment2-line1',),
		('segment2-line2',),
	]
	s.insert(0, l2)
	test/s[:] == (l2 + l)
	test/s[:2] == l2
	test/s[:3] == l2 + l[:1] # crosses over
	test/s[1:3] == l2[1:] + l[:1] # crosses over

	s.partition()
	test/s[:] == (l2 + l)
	test/s.sequences == [l2 + l]

	s.clear()
	test/s[:] == []

	s[0:0] = l
	test/s[:] == l

def test_segments_sequence_features(test):
	l = list(range(1057))
	s = library.Segments(l)
	test/len(s) == 1057
	test/list(s[:]) == l

	s[3:3] = [4,3,2]
	l[3:3] = [4,3,2]
	test/list(s[:]) == l

	seqs = (l, s)

	for x in seqs:
		x[4:8] = x[22:26]

	test/seqs[0] == list(seqs[1])

	test/seqs[0][1000:1200] == seqs[1][1000:1200]

def test_select(test):
	seg = library.Segments(list(range(439)))
	print(library.address(seg.sequences, 400, 445))
	print(list(seg.select(400, 445)), list(range(400, 440)))
	test/list(seg.select(400, 445)) == list(range(400, 439))

def test_sequence(test):
	return
	s = library.Sequence()
	f = library.Field()
	s.insert(f)

	test/s.length() == 0

	test/list(s.value()) == [(f, (s,))]
	
	s.clear()
	test/tuple(s.value()) == ()
	test/s.length() == 0
	test/s.position.get() == 0

	s.insert(f)

	test/s.find(0) == None
	test/s.offset(f) == (0, 0, 0)
	test/list(s.value()) == [(f, (s,))]
	test/s.length() == 0

	f.insert("test")
	test/s.length() == 4

	test/s.find(0) == f
	test/s.find(1) == f
	test/s.find(2) == f
	test/s.find(3) == f
	test/s.find(4) == None

	f2 = library.Field()
	s.insert(f2)
	test/list(s.value()) == [(f, (s,)), (f2, (s,))]

	f2.insert(".")
	test/str(s) == "test."
	test/s.find(4) == f2

	# position is at end
	test/s.offset(f) == (0, 4, 4)
	f.move(0, 1)
	test/s.offset(f) == (0, 0, 4)

	test/s.offset(f2) == (4, 5, 5)
	s.move(1, 1)
	test/s.selection == f2
	s.move(1)
	test/s.selection == None # position at edge

	f3 = library.Field()
	s.insert(f3)
	f3.insert("fields")
	test/str(s) == "test.fields"
	test/list(s.value()) == [(f, (s,)), (f2, (s,)), (f3, (s,))]

doc = """import foo
import bar
import nothing

def function(a, b):
	pass
	
class Class():

	def __init__(self):
		pass
		pass
		if 0:
			pass
		pass

"""

def test_block(test):
	return
	lines = [library.Sequence(library.parse(line)) for line in doc.split('\n')]

	# contiguous
	start, stop = library.block(lines, 1, 0, len(lines), library.indentation_block)
	test/start == 0
	test/stop == 2

	start, stop = library.block(lines, 12, 0, len(lines), library.indentation_block)
	test/start == 9
	test/stop == len(lines)

if __name__ == '__main__':
	from ...development import libtest
	import sys; libtest.execute(sys.modules[__name__])
