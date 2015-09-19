"""
fault.io sectors Scheduling Daemon

scheduled is the fault.io implementation of cron and quartz.
"""
import sys

class Scheduled(object):
	"""
	API Set bound to a set of Interfaces.
	"""

	def __init__(self):
		pass

@boot
def main(sector):
	print('EXECUTED!')
	sys.stderr.flush()
