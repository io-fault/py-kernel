"""
fault.io interactive console
"""
from ..console import library as libconsole

name = 'console'
initialize = libconsole.initialize

if __name__ == '__main__':
	from .. import library as iolib
	iolib.execute(console = (libconsole.initialize,))
